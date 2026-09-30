"""Search/discovery providers. Each was verified against the live environment before inclusion (see HACKATHON_PROGRESS.md).

Every provider returns (results, note). A result: {url, title, snippet, text?} — `text` is set when the provider already
returns the full evidence (community APIs), so no page fetch is needed. Providers raise ProviderError on failure."""
import asyncio, html, os, re, time
from urllib.parse import parse_qs, unquote, urlparse
import httpx

SEARXNG = os.getenv("SEARXNG_URL", "http://localhost:9090")
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
API_UA = "ResearchOps/0.1 (business research; local hackathon app)"


class ProviderError(Exception):
    def __init__(self, reason, cooldown_s=None):
        super().__init__(reason)
        self.reason, self.cooldown_s = reason, cooldown_s


_last_call: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}
MIN_INTERVAL = {"searxng:yandex": 1.5, "reddit_pullpush": 1.0, "wikipedia_links": 0.3}


async def _paced(name):
    """Per-provider politeness: request *starts* are at least MIN_INTERVAL apart; requests themselves may overlap."""
    lock = _locks.setdefault(name, asyncio.Lock())
    async with lock:
        wait = _last_call.get(name, 0) + MIN_INTERVAL.get(name, 1) - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call[name] = time.time()
    return None


def _done(name, lock):
    pass


def _text(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h or "", flags=re.S | re.I)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))).strip()


# ---------- general web search ----------
async def searxng(engine: str, query: str):
    name = f"searxng:{engine}"
    lock = await _paced(name)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{SEARXNG}/search", params={"q": query, "format": "json", "engines": engine, "language": "en"},
                            headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"})
    except httpx.HTTPError as e:
        raise ProviderError(f"SearXNG unreachable: {type(e).__name__}", 120)
    finally:
        _done(name, lock)
    if r.status_code != 200:
        raise ProviderError(f"SearXNG HTTP {r.status_code}", 120)
    j = r.json()
    down = {e[0]: e[1] for e in j.get("unresponsive_engines", [])}
    if engine in down:
        raise ProviderError(f"{engine}: {down[engine]}", 600)
    res = [{"url": x["url"], "title": x.get("title", ""), "snippet": x.get("content", "")} for x in j.get("results", [])]
    return res, ""


# ---------- community evidence (full text returned directly) ----------
def _mentions(text, name):
    return name.lower() in (text or "").lower()


async def reddit_pullpush(name: str):
    """Reddit posts + comments via the PullPush archive API (reddit.com itself blocks this environment)."""
    lock = await _paced("reddit_pullpush")
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": API_UA}) as c:
            rs = await c.get("https://api.pullpush.io/reddit/search/submission/", params={"q": name, "size": 40})
            rc = await c.get("https://api.pullpush.io/reddit/search/comment/", params={"q": name, "size": 100})
    except httpx.HTTPError as e:
        raise ProviderError(f"network: {type(e).__name__}", 300)
    finally:
        _done("reddit_pullpush", lock)
    if rs.status_code != 200 or rc.status_code != 200:
        raise ProviderError(f"HTTP {rs.status_code}/{rc.status_code}", 600)
    threads = {}
    for p in rs.json().get("data", []):
        body = f"{p.get('title', '')}\n\n{p.get('selftext', '') if p.get('selftext') not in ('[removed]', '[deleted]') else ''}"
        if not _mentions(body, name):
            continue
        t = threads.setdefault(p["id"], {"url": f"https://www.reddit.com{p.get('permalink', '')}", "title": f"r/{p.get('subreddit')}: {p.get('title', '')}",
                                         "parts": [], "subreddit": p.get("subreddit")})
        t["parts"].append(body)
    for cm in rc.json().get("data", []):
        body = cm.get("body", "")
        if not _mentions(body, name) or len(body) < 60 or body in ("[removed]", "[deleted]"):
            continue
        tid = (cm.get("link_id") or "").replace("t3_", "")
        link = cm.get("permalink", "")
        t = threads.setdefault(tid or cm["id"], {"url": f"https://www.reddit.com{link.rsplit('/', 2)[0] if link else ''}/",
                                                 "title": f"r/{cm.get('subreddit')} discussion", "parts": [], "subreddit": cm.get("subreddit")})
        t["parts"].append(body)
    res = [{"url": t["url"], "title": t["title"], "snippet": t["parts"][0][:200], "text": "\n\n".join(t["parts"])}
           for t in threads.values() if sum(len(x) for x in t["parts"]) >= 150]
    res.sort(key=lambda x: -len(x["text"]))
    return res[:12], f"{len(threads)} threads mentioned '{name}'"



# ---------- reference articles (full text, no search engine involved) ----------
async def wikipedia_articles(titles: list[str]):
    lock = await _paced("wikipedia_articles")
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": API_UA}) as c:
            out = []
            errors = []
            for title in titles:   # the API returns full-text extracts for only one page per request
                await asyncio.sleep(0.4)
                r = await c.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "prop": "extracts", "explaintext": 1,
                                                                             "titles": title, "format": "json", "redirects": 1})
                if r.status_code != 200:
                    errors.append(f"{title}: HTTP {r.status_code}")
                    if r.status_code == 429:
                        await asyncio.sleep(3)
                    continue
                for p in r.json().get("query", {}).get("pages", {}).values():
                    t = p.get("extract") or ""
                    t = re.split(r"\n== (See also|References|Notes|Further reading|External links|Bibliography) ==", t)[0]
                    if len(t) >= 400:
                        out.append({"url": f"https://en.wikipedia.org/wiki/{p['title'].replace(' ', '_')}", "title": f"Wikipedia: {p['title']}",
                                    "snippet": t[:200], "text": t})
    except httpx.HTTPError as e:
        raise ProviderError(f"network: {type(e).__name__}", 120)
    finally:
        _done("wikipedia_articles", lock)
    if not out and errors:
        raise ProviderError("; ".join(errors[:3]), 300)
    return out, f"{len(out)} articles with text" + (f"; {len(errors)} failed ({errors[0]})" if errors else "")


# ---------- curated links (no search engine involved) ----------
SKIP_LINK = re.compile(r"books\.google|doi\.org|jstor|worldcat|archive\.org|gutenberg|mailto:|\.pdf$|geohack|wikidata|wikimedia|"
                       r"openstreetmap|google\.com/maps|twitter|facebook|instagram|youtube|isbn|oclc|semanticscholar|/search\?", re.I)


async def wiki_links(site: str, title: str):
    name = "wikipedia_links"
    lock = await _paced(name)
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": API_UA}) as c:
            r = await c.get(f"https://{site}/w/api.php", params={"action": "query", "titles": title, "prop": "extlinks", "ellimit": 500,
                                                                "format": "json", "redirects": 1})
    except httpx.HTTPError as e:
        raise ProviderError(f"network: {type(e).__name__}", 120)
    finally:
        _done(name, lock)
    pages = list(r.json().get("query", {}).get("pages", {}).values())
    links = [x["*"] for p in pages for x in p.get("extlinks", [])]
    links = [("https:" + u if u.startswith("//") else u) for u in links if u.startswith(("http", "//")) and not SKIP_LINK.search(u)]
    return [{"url": u, "title": urlparse(u).netloc, "snippet": f"linked from the {site.split('.')[1].title()} article '{title}'"}
            for u in dict.fromkeys(links)], f"{len(links)} external links"
