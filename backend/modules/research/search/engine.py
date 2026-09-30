"""Search orchestration: cache-first, health-aware provider fallback, genericity detection, page fetching with cache
and Web Archive fallback. Everything it does is recorded so the research console can show it."""
import asyncio, re, time
from urllib.parse import urlparse
import httpx, trafilatura
from . import cache, health, providers as P
from ...store import bucket
from .providers import ProviderError

WEB_ORDER = ["searxng:yandex"] + (["serpapi"] if P.SERPAPI_KEY else []) + ["duckduckgo"]   # fall through in this order
QUERY_SPECIFIC = {"searxng:yandex", "serpapi", "duckduckgo"}
MIN_GOOD = 5
FALLBACK_TIMEOUT = 8   # seconds each for the browser and the Web Archive attempts on a blocked page
BROWSER_UA = P.BROWSER_UA


def _call(provider, arg):
    if provider.startswith("searxng:"):
        return P.searxng(provider.split(":", 1)[1], arg)
    return {"reddit_pullpush": P.reddit_pullpush, "duckduckgo": P.duckduckgo, "serpapi": P.serpapi}[provider](arg)


class SearchSession:
    def __init__(self):
        self.attempts = []                 # every provider call/cache hit, in order
        self.prev_urls: dict[str, list[set]] = {}
        self.generic: set[str] = set()
        self.cache_hits = {"search": 0, "pages": 0}
        self.live_calls = {"search": 0, "pages": 0}
        self.browser_used = {"tried": 0, "recovered": 0}
        self._browser = None
        self._browser_lock = asyncio.Lock()

    async def _browser_session(self):
        """One shared headless browser per research run, started only when a page is blocked (~0.75 s startup)."""
        async with self._browser_lock:
            if self._browser is None:
                from scrapling.fetchers import AsyncStealthySession
                # speed: no resources/ads, no network-idle wait; anti-detection flags on; 2 s wait for JS-rendered content
                self._browser = AsyncStealthySession(max_pages=8, headless=True, disable_resources=True, block_ads=True,
                                                     network_idle=False, load_dom=False, wait=2000, timeout=15000, solve_cloudflare=False,
                                                     google_search=True, block_webrtc=True, hide_canvas=True, allow_webgl=True)
                await self._browser.__aenter__()
            return self._browser

    async def close(self):
        if self._browser is not None:
            try:
                await self._browser.__aexit__(None, None, None)
            finally:
                self._browser = None

    async def _one(self, provider, key_arg, query_label, use_cache=True):
        key = f"{provider}|{key_arg}"
        if use_cache and (hit := cache.get("search", key, cache.SEARCH_TTL)):
            self.cache_hits["search"] += 1
            a = {"provider": provider, "query": query_label, "status": "cached", "n": len(hit["results"]),
                 "note": f"cached result from {time.strftime('%Y-%m-%d %H:%M', time.localtime(hit['retrieved_at']))}", "ms": 0}
            self.attempts.append(a)
            return hit["results"], a
        if not health.available(provider):
            s = health.get(provider)
            a = {"provider": provider, "query": query_label, "status": "skipped", "n": 0,
                 "note": f"{s['status']}: {s['reason']}" + (f" (cooling down {int(s['cooldown_until'] - time.time())} s)" if s["cooldown_until"] > time.time() else ""), "ms": 0}
            self.attempts.append(a)
            return None, a
        t0 = time.time()
        self.live_calls["search"] += 1
        try:
            results, note = await _call(provider, key_arg)
        except ProviderError as e:
            health.fail(provider, e.reason, e.cooldown_s)
            a = {"provider": provider, "query": query_label, "status": "failed", "n": 0, "note": e.reason, "ms": int((time.time() - t0) * 1000)}
            self.attempts.append(a)
            return None, a
        except Exception as e:
            health.fail(provider, f"{type(e).__name__}: {str(e)[:100]}")
            a = {"provider": provider, "query": query_label, "status": "failed", "n": 0, "note": f"{type(e).__name__}", "ms": int((time.time() - t0) * 1000)}
            self.attempts.append(a)
            return None, a
        if results:
            cache.put("search", key, {"provider": provider, "query": key_arg, "results": results})
            health.ok(provider, note or f"{len(results)} results")
        else:
            health.degraded(provider, "returned no results")
        a = {"provider": provider, "query": query_label, "status": "ok" if results else "empty", "n": len(results), "note": note,
             "ms": int((time.time() - t0) * 1000)}
        self.attempts.append(a)
        return results, a

    def _check_generic(self, provider, urls: set):
        """A provider that returns the same pages for different questions is not really searching them."""
        prev = self.prev_urls.setdefault(provider, [])
        same = [p for p in prev if urls and len(urls & p) / len(urls | p) >= 0.7]
        prev.append(urls)
        if len(same) >= 1 and provider not in self.generic:
            self.generic.add(provider)
            health.degraded(provider, "returns the same results for different queries (ignores query wording)")
        return provider in self.generic

    async def web(self, query: str) -> dict:
        """Best available results for one query. Falls through providers until results are specific and plentiful."""
        tried = []
        for prov in WEB_ORDER:
            if prov in self.generic and tried:
                continue
            res, a = await self._one(prov, query, query)
            tried.append(a)
            if not res:
                continue
            generic = self._check_generic(prov, {r["url"] for r in res})
            a["generic"] = generic
            if len(res) >= MIN_GOOD and not generic:
                return {"results": res, "provider": prov, "attempts": tried, "specific": prov in QUERY_SPECIFIC, "cached": a["status"] == "cached"}
            best = res
            if prov == WEB_ORDER[-1]:
                return {"results": best, "provider": prov, "attempts": tried, "specific": False, "cached": a["status"] == "cached"}
        # nothing specific: return the best non-empty attempt, if any
        for a in tried:
            if a["n"]:
                hit = cache.get("search", f"{a['provider']}|{query}", cache.SEARCH_TTL)
                return {"results": hit["results"] if hit else [], "provider": a["provider"], "attempts": tried, "specific": False, "cached": a["status"] == "cached"}
        return {"results": [], "provider": None, "attempts": tried, "specific": False, "cached": False}

    async def community(self, provider, name):
        res, a = await self._one(provider, name, f"{provider}: {name}")
        return {"results": res or [], "provider": provider, "attempts": [a], "cached": a["status"] == "cached"}

    async def links(self, site, title):
        prov = "wikipedia_links"
        key = f"{prov}|{title}"
        if hit := cache.get("search", key, cache.SEARCH_TTL):
            self.cache_hits["search"] += 1
            a = {"provider": prov, "query": title, "status": "cached", "n": len(hit["results"]), "note": "cached", "ms": 0}
            self.attempts.append(a)
            return {"results": hit["results"], "provider": prov, "attempts": [a], "cached": True}
        try:
            self.live_calls["search"] += 1
            res, note = await P.wiki_links(site, title)
            health.ok(prov, note)
            cache.put("search", key, {"provider": prov, "query": title, "results": res})
            a = {"provider": prov, "query": title, "status": "ok", "n": len(res), "note": note, "ms": 0}
        except Exception as e:
            health.fail(prov, str(e)[:100])
            res, a = [], {"provider": prov, "query": title, "status": "failed", "n": 0, "note": str(e)[:100], "ms": 0}
        self.attempts.append(a)
        return {"results": res, "provider": prov, "attempts": [a], "cached": False}

    async def articles(self, titles: list[str]):
        key = "wikipedia_articles|" + "|".join(sorted(titles))
        if hit := cache.get("search", key, cache.SEARCH_TTL):
            self.cache_hits["search"] += 1
            a = {"provider": "wikipedia_articles", "query": f"{len(titles)} titles", "status": "cached", "n": len(hit["results"]), "note": "cached", "ms": 0}
            self.attempts.append(a)
            return {"results": hit["results"], "provider": "wikipedia_articles", "attempts": [a], "cached": True}
        self.live_calls["search"] += 1
        try:
            res, note = await P.wikipedia_articles(titles)
            health.ok("wikipedia_articles", note)
            cache.put("search", key, {"provider": "wikipedia_articles", "query": titles, "results": res})
            a = {"provider": "wikipedia_articles", "query": f"{len(titles)} titles", "status": "ok", "n": len(res), "note": note, "ms": 0}
        except ProviderError as e:
            health.fail("wikipedia_articles", e.reason, e.cooldown_s)
            res, a = [], {"provider": "wikipedia_articles", "query": f"{len(titles)} titles", "status": "failed", "n": 0, "note": e.reason, "ms": 0}
        self.attempts.append(a)
        return {"results": res, "provider": "wikipedia_articles", "attempts": [a], "cached": a["status"] == "cached"}

    # ---------- pages ----------
    async def fetch(self, url: str) -> dict:
        """-> {ok, title, text, cached, via, error}. Cache-first; on block/timeout tries the Internet Archive copy."""
        if hit := cache.get("pages", url, cache.PAGE_TTL):
            self.cache_hits["pages"] += 1
            return {"ok": True, "title": hit["title"], "text": hit["text"], "cached": True, "via": hit.get("via", "direct"),
                    "retrieved_at": hit["retrieved_at"]}
        if dead := cache.get("dead", url, 86400):   # remembered permanent failure (404/410) — don't hammer it again
            self.cache_hits["pages"] += 1
            return {"ok": False, "error": dead["error"] + " (remembered)", "archive_error": dead.get("archive_error"), "cached": True}
        self.live_calls["pages"] += 1
        err = None
        try:
            title, text = await _fetch_direct(url)
            cache.put("pages", url, {"title": title, "text": text, "via": "direct"})
            return {"ok": True, "title": title, "text": text, "cached": False, "via": "direct"}
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"
            permanent = isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (404, 410)
            blocked = (isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (202, 401, 403, 429, 503)) or isinstance(e, ValueError)
        if blocked and health.available("scrapling_browser"):
            # anti-bot / JS-rendered page: retry in a real headless browser (Scrapling), resources and ads blocked
            self.browser_used["tried"] += 1
            try:
                page = await asyncio.wait_for((await self._browser_session()).fetch(url), FALLBACK_TIMEOUT)
                html = getattr(page, "html_content", None) or page.body.decode("utf8", "ignore")
                if page.status >= 400:
                    raise ValueError(f"browser got HTTP {page.status}")
                title, text = await asyncio.to_thread(_extract, html, url, "headless browser (Scrapling)")
                self.browser_used["recovered"] += 1
                health.ok("scrapling_browser", "recovered a blocked page")
                cache.put("pages", url, {"title": title, "text": text, "via": "headless browser (Scrapling)"})
                return {"ok": True, "title": title, "text": text, "cached": False, "via": "headless browser (Scrapling)", "direct_error": err}
            except Exception as eb:
                err += f" · browser: {type(eb).__name__}: {str(eb)[:80]}"
        try:
            title, text, snap = await asyncio.wait_for(_fetch_archive(url), FALLBACK_TIMEOUT)
            cache.put("pages", url, {"title": title, "text": text, "via": f"web.archive.org ({snap})"})
            return {"ok": True, "title": title, "text": text, "cached": False, "via": f"web.archive.org ({snap})", "direct_error": err}
        except Exception as e2:
            aerr = f"{type(e2).__name__}: {str(e2)[:80]}"
            if permanent:
                cache.put("dead", url, {"error": err, "archive_error": aerr})
            return {"ok": False, "error": err, "archive_error": aerr, "cached": False}


def _extract(html_text, url, via):
    bucket.put(url, html_text, via)   # raw page into the global bucket, before any parsing
    text = trafilatura.extract(html_text, include_comments=True, include_tables=False, favor_recall=True)
    if not text or len(text) < 300:
        raise ValueError("no substantial article text extracted")
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    return (m[1].strip() if m else ""), text


async def _fetch_direct(url):
    async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers={"User-Agent": BROWSER_UA, "Accept-Language": "en"}) as c:
        r = await c.get(url)
    r.raise_for_status()
    if "html" not in r.headers.get("content-type", "html"):
        raise ValueError(f"not HTML ({r.headers.get('content-type')})")
    return await asyncio.to_thread(_extract, r.text, url, "direct")


async def _fetch_archive(url):
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": P.API_UA}) as c:
        r = await c.get("https://archive.org/wayback/available", params={"url": url})
        snap = (r.json().get("archived_snapshots") or {}).get("closest")
        if not snap or not snap.get("available"):
            raise ValueError("no archived copy")
        raw = re.sub(r"/web/(\d+)/", r"/web/\1id_/", snap["url"])   # id_ = original page without the archive toolbar
        r2 = await c.get(raw)
        r2.raise_for_status()
    title, text = await asyncio.to_thread(_extract, r2.text, url, f"web.archive.org ({snap['timestamp'][:8]})")
    return title, text, snap["timestamp"][:8]


# ---------- overall status ----------
def overall(session_stats: dict | None = None) -> dict:
    """HEALTHY / DEGRADED / OFFLINE, from real provider states (and this run's outcomes when given)."""
    snap = health.snapshot()
    live_specific = [p for p in QUERY_SPECIFIC if snap.get(p, {}).get("status") == "healthy" and not snap[p]["cooling_down_s"]]
    fallbacks = [p for p in ("reddit_pullpush", "wikipedia_links", "wikipedia_articles")
                 if snap.get(p, {}).get("status") in ("healthy", "degraded") and not snap.get(p, {}).get("cooling_down_s")]
    if session_stats:
        ratio = session_stats["specific_queries"] / max(1, session_stats["queries"])
        cached_share = session_stats["cached_queries"] / max(1, session_stats["queries"])
        if ratio >= 0.7:
            label, why = "HEALTHY", f"{session_stats['specific_queries']}/{session_stats['queries']} queries answered by a query-specific search engine"
        elif ratio > 0 or session_stats["community_docs"] or session_stats["curated_links"]:
            label, why = "DEGRADED", (f"only {session_stats['specific_queries']}/{session_stats['queries']} queries got query-specific results; "
                                      f"relied on fallbacks (community APIs, curated links, reference articles)")
        else:
            label, why = "OFFLINE", "no search provider returned results"
        if cached_share >= 0.5:
            why += f" · {cached_share:.0%} of queries served from cache (real earlier results)"
        return {"label": label, "why": why}
    if live_specific:
        return {"label": "HEALTHY", "why": f"query-specific search available: {', '.join(sorted(live_specific))}"}
    if fallbacks:
        return {"label": "DEGRADED", "why": f"no query-specific web search right now; fallbacks available: {', '.join(fallbacks)}"}
    if not snap:
        return {"label": "UNKNOWN", "why": "no provider has been used or probed yet"}
    return {"label": "OFFLINE", "why": "no provider currently reachable — research would use cached results only"}


async def probe() -> dict:
    """Real, minimal probe of each provider (bypasses cache). Rate-limited by the providers' own pacing."""
    s = SearchSession()
    out = {}
    for prov, arg in (("searxng:yandex", "electric vehicle market India"), ("reddit_pullpush", "electric scooter")):
        res, a = await s._one(prov, arg, f"probe: {arg}", use_cache=False)
        out[prov] = a
    try:
        res, note = await P.wiki_links("en.wikipedia.org", "Electric vehicle")
        health.ok("wikipedia_links", note); out["wikipedia_links"] = {"status": "ok", "n": len(res)}
    except Exception as e:
        health.fail("wikipedia_links", str(e)[:100]); out["wikipedia_links"] = {"status": "failed", "note": str(e)[:100]}
    return out
