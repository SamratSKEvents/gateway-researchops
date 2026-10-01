"""Collection stages of a research run (plan, search, select, fetch, claims, index). Every stage emits an event carrying the real data it produced, so the UI can audit it."""
import asyncio, hashlib, json, time, traceback, uuid
from collections import Counter
from urllib.parse import urlparse
from . import extract as X, _llm as llm
from .paths import RUNS
from .search import SearchSession, overall, health

FALLBACK_TASKS = [  # used only when the model cannot decompose the question
    ("market size growth", "How big is the market and how fast is it growing?"),
    ("competitors", "Who are the existing competitors?"),
    ("pricing", "What do competitors charge?"),
    ("customers demand", "Who are the customers and what do they want?"),
    ("regulation policy", "What regulations or policies apply?"),
    ("challenges risks", "What has gone wrong for others?"),
]
MAX_SOURCES = 32
PLAN_SCHEMA = {"type": "object", "required": ["subject", "keywords", "tasks"], "properties": {
    "subject": {"type": "string", "maxLength": 60},
    "keywords": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 40}},
    "tasks": {"type": "array", "minItems": 4, "maxItems": 8, "items": {"type": "object", "required": ["question", "query", "agent"], "properties": {
        "question": {"type": "string", "maxLength": 140}, "query": {"type": "string", "maxLength": 90},
        "agent": {"enum": ["market", "competitor", "customer", "regulation"]}}}}}}


class Run:
    def __init__(self, query):
        self.id = uuid.uuid4().hex[:10]
        self.query = query.strip()
        self.created = time.time()
        self.events, self.subscribers = [], set()
        self.status = "running"
        self.sources, self.claims, self.docs = {}, {}, {}
        self.result = {}

    # ---------- event plumbing ----------
    def emit(self, stage, title, status, summary="", data=None):
        ev = {"i": len(self.events), "t": round(time.time() - self.created, 1), "stage": stage, "title": title,
              "status": status, "summary": summary, "data": data}
        self.events.append(ev)
        for q in list(self.subscribers):
            q.put_nowait(ev)

    async def stage(self, key, title, fn, required=False):
        self.emit(key, title, "running")
        t0 = time.time()
        try:
            summary, data = await fn()
            self.emit(key, title, "done", f"{summary} ({time.time() - t0:.1f}s)", data)
            return True
        except Exception as e:
            self.emit(key, title, "failed", f"{type(e).__name__}: {e}", {"traceback": traceback.format_exc()[-2000:]})
            if required:
                raise
            return False

    def add_source(self, url, title, stype=None, origin="search", **kw):
        for s in self.sources.values():
            if s["url"] == url:
                return s["id"]
        sid = f"s{len(self.sources) + 1}"
        stype = stype or X.classify_source(url)
        self.sources[sid] = {"id": sid, "url": url, "title": title, "type": stype, "type_label": X.SOURCE_TYPES[stype][1],
                             "authority": X.SOURCE_TYPES[stype][0], "origin": origin, "domain": urlparse(url).netloc.replace("www.", ""),
                             "status": "registered", "queries": [], "n_claims": 0, **kw}
        return sid

    def add_claim(self, text, sid, a, task_ids, extra=None):
        cid = f"c{len(self.claims) + 1}"
        self.claims[cid] = {"id": cid, "text": text, "source": sid, "tasks": task_ids, **a, **(extra or {})}
        self.sources[sid]["n_claims"] += 1
        return cid

    # ---------- collection stages (orchestrated by director.Director) ----------
    async def plan(self):
        ctx = f"Research question: {self.query}" + (f"\nUser's goal: {self.goal}" if getattr(self, "goal", None) else "")
        sys = ("You plan business research. Break the research question into 5-8 focused, non-overlapping research tasks. "
               "Each task has a question, a short web search query (keywords, no quotes), and the specialist who owns it: market (size, growth, "
               "trends), competitor (named companies, their offers and prices), customer (users' needs, behaviour, willingness to pay), "
               "regulation (laws, permits, policy, operational risk). "
               "subject = the core topic in 2-4 words; keywords = distinctive terms (companies, products, places) a relevant page must mention.")
        try:
            j = await llm.chat_json(sys, ctx, 900, PLAN_SCHEMA)
            tasks = [{"question": str(t["question"]), "q": str(t["query"]), **({"agent": t["agent"], "agent_by": "planner"} if t.get("agent") else {})}
                     for t in j["tasks"] if t.get("query")]
            subject, keywords, how = str(j["subject"]), [str(k) for k in j["keywords"] if k], f"planned by {llm.MODEL}"
        except Exception as e:   # model down: generic decomposition on the raw question
            subject, keywords, how = self.query[:60], [], f"model unavailable ({type(e).__name__}); generic task template"
            tasks = []
        if not tasks:
            tasks = [{"question": question, "q": f"{self.query} {topic}"} for topic, question in FALLBACK_TASKS]
        self.queries = [{"id": f"t{i + 1}", **t} for i, t in enumerate(tasks)]
        self.subject = subject
        self.key_norms = sorted({X.norm(k) for k in [subject, *keywords] if len(X.norm(k)) >= 3})
        self.result["plan"] = {"subject": subject, "keywords": keywords, "tasks": self.queries, "how": how}
        return f"{len(self.queries)} research tasks ({how})", self.result["plan"]

    async def search(self, queries, community=True):
        """Web queries (health-aware fallback) + community discussions. Paced on purpose. One call per research round."""
        if not getattr(self, "search_session", None):
            self.search_session = SearchSession()
        ss = self.search_session
        self.search_results = {}
        pre = overall()
        self.emit("search", "Search health before starting", "progress", f"{pre['label']}: {pre['why']}", {"health": health.snapshot()})
        counters = {"specific": 0, "cached": 0, "community": 0, "done": 0}
        web_sem = asyncio.Semaphore(2)

        async def one_web(q):
            async with web_sem:
                r = await ss.web(q["q"])
                on_topic = sum(self._relevant(f"{x.get('title', '')} {x.get('snippet', '')} {x['url']}") for x in r["results"])
                if r["results"] and on_topic / len(r["results"]) < 0.3 and r["provider"] != "duckduckgo":
                    res, a = await ss._one("duckduckgo", q["q"], q["q"])     # provider answered off-topic: ask the fallback
                    r["attempts"].append(a)
                    if res:
                        r.update(results=res, provider="duckduckgo", cached=a["status"] == "cached")
            counters["specific"] += r["specific"]; counters["cached"] += r["cached"]; counters["done"] += 1
            self.search_results[q["q"]] = {"ok": bool(r["results"]), "results": r["results"], "provider": r["provider"], "task": q["id"]}
            used = r["provider"] or "none"
            flags = [x for x in ("cached" if r["cached"] else "", "generic results" if not r["specific"] and r["results"] else "") if x]
            self.emit("search", f"Searched ({counters['done']}/{len(queries)}): {q['q']}", "progress",
                      f"{len(r['results'])} results via {used}" + (f" ({', '.join(flags)})" if flags else ""),
                      {"query": q["q"], "question": q["question"], "ok": bool(r["results"]), "results": r["results"], "provider": used,
                       "attempts": r["attempts"], "specific": r["specific"], "cached": r["cached"]})

        async def one_community(nm):
            r = await ss.community("reddit_pullpush", nm)
            self.search_results[f"community: Reddit: {nm}"] = {"ok": bool(r["results"]), "results": r["results"], "provider": "reddit_pullpush"}
            counters["community"] += len(r["results"])
            self.emit("search", f"Community: Reddit (via PullPush) '{nm}'", "progress", f"{len(r['results'])} discussions" + (" (cached)" if r["cached"] else ""),
                      {"query": f"Reddit: {nm}", "question": "What do people say about it?", "ok": bool(r["results"]), "results": r["results"],
                       "provider": "reddit_pullpush", "attempts": r["attempts"], "cached": r["cached"]})

        await asyncio.gather(*(one_web(q) for q in queries), *([one_community(" ".join(self.subject.split()[:2]))] if community else []))
        self.search_stats = {"queries": len(queries), "specific_queries": counters["specific"], "cached_queries": counters["cached"],
                             "community_docs": counters["community"], "curated_links": 0,
                             "results": sum(len(v["results"]) for v in self.search_results.values()),
                             "distinct_urls": len({x["url"] for v in self.search_results.values() for x in v["results"]}),
                             "provider_calls": dict(Counter(a["provider"] + ":" + a["status"] for a in ss.attempts))}
        st = overall(self.search_stats)
        self.result["search_health"] = {**st, "stats": {k: v for k, v in self.search_stats.items() if k != "provider_calls"},
                                        "provider_calls": self.search_stats["provider_calls"], "providers": health.snapshot()}
        if not self.search_stats["results"]:
            raise RuntimeError(f"SEARCH {st['label']}: {st['why']}")
        return (f"SEARCH {st['label']} — {self.search_stats['results']} results, {self.search_stats['distinct_urls']} distinct URLs; "
                f"{counters['specific']}/{len(queries)} queries query-specific, {counters['cached']} from cache; {counters['community']} community discussions",
                {"health": st, "stats": self.search_stats, "attempts": ss.attempts, "providers": health.snapshot()})

    def _relevant(self, text):
        n = X.norm(text)
        return not self.key_norms or any(k in n for k in self.key_norms)

    async def select(self, budget=MAX_SOURCES):
        """Pick pages to read from this round's results; pages already known from earlier rounds are skipped."""
        known = {s["url"] for s in self.sources.values()}
        pool = {}
        for q, r in self.search_results.items():
            for rank, res in enumerate(r["results"]):
                if res["url"] in known:
                    continue
                p = pool.setdefault(res["url"], {"url": res["url"], "title": res["title"], "snippets": [], "queries": [], "tasks": set(),
                                                 "best_rank": 99, "text": res.get("text"), "provider": r["provider"]})
                p["queries"].append(q); p["snippets"].append(res.get("snippet", "")); p["best_rank"] = min(p["best_rank"], rank)
                if r.get("task"):
                    p["tasks"].add(r["task"])
        scored = []
        for p in pool.values():
            community = p["provider"] == "reddit_pullpush"
            stype = "forum" if community else X.classify_source(p["url"])
            relevant = self._relevant(p["title"] + " " + " ".join(p["snippets"]) + " " + (p["text"] or "")[:3000] + " " + p["url"])
            skip = next((d for d in X.SKIP_FETCH if d in p["url"]), None)
            score = (len(p["queries"]) * 1.5 + X.SOURCE_TYPES[stype][0] * 2 + (10 - min(p["best_rank"], 10)) * 0.2
                     + (stype in ("official", "news", "research")) * 1.0)
            scored.append({**p, "type": stype, "relevant": relevant, "skip_reason": f"not fetchable ({skip})" if skip else None,
                           "score": round(score, 2) if relevant else 0})
        scored.sort(key=lambda p: -p["score"])
        per_domain, per_type, chosen, inline = Counter(), Counter(), [], []
        type_cap = {"commercial": 3, "review": 4}
        for p in scored:
            dom = urlparse(p["url"]).netloc
            if not p["relevant"]:
                p["decision"] = "rejected: does not mention the research subject"
            elif p["text"]:
                if len(inline) < 14:
                    p["decision"] = "accepted: full text from community API"; inline.append(p)
                else:
                    p["decision"] = "not used: community budget reached"
            elif p["skip_reason"]:
                p["decision"] = f"snippet only: {p['skip_reason']}"
            elif per_domain[dom] >= 3:
                p["decision"] = "rejected: already 3 sources from this domain"
            elif per_type[p["type"]] >= type_cap.get(p["type"], 99):
                p["decision"] = f"rejected: enough {p['type']} sources (diversity cap)"
            elif len(chosen) >= budget:
                p["decision"] = "not read: source budget reached (snippet kept)"
            else:
                p["decision"] = "selected"; chosen.append(p); per_domain[dom] += 1; per_type[p["type"]] += 1
            if p["relevant"]:
                sid = self.add_source(p["url"], p["title"], p["type"], "community" if p["text"] else "search")
                self.sources[sid].update(queries=p["queries"], tasks=sorted(p["tasks"]), provider=p["provider"],
                                         snippets=list(dict.fromkeys(s for s in p["snippets"] if s)),
                                         status="selected" if p["decision"] == "selected" else "snippet")
                if p["text"] and p["decision"].startswith("accepted"):
                    self.docs[sid] = p["text"][:60000]
                    self.sources[sid].update(status="fetched", chars=len(p["text"]), via=f"{p['provider']} API")
        self.selected = [self.add_source(p["url"], p["title"]) for p in chosen]
        # reserve list: next-best readable pages, used to replace pages that fail to fetch
        self.backup = [self.add_source(p["url"], p["title"]) for p in scored
                       if p["decision"].startswith("not read: source budget") and per_domain[urlparse(p["url"]).netloc] < 3][:20]
        types = Counter(p["type"] for p in chosen + inline)
        return (f"{len(pool)} distinct URLs → {len(chosen)} pages to read + {len(inline)} full-text community discussions "
                f"({', '.join(f'{v} {k}' for k, v in types.most_common())})",
                {"candidates": [{k: p[k] for k in ("url", "title", "type", "score", "decision", "provider")} for p in scored[:200]]})

    async def fetch(self):
        sem = asyncio.Semaphore(12)
        ss = self.search_session

        async def one(sid):
            s = self.sources[sid]
            async with sem:
                r = await ss.fetch(s["url"])
            if r["ok"]:
                self.docs[sid] = r["text"][:60000]
                s.update(status="fetched", chars=len(r["text"]), fetched_title=r["title"], via=r["via"], cached=r["cached"])
                self.emit("fetch", f"Read {s['domain']}", "progress", f"{len(r['text']):,} chars" + (" (cached copy)" if r["cached"] else "")
                          + (f" via {r['via']}" if r["via"] != "direct" else ""),
                          {"source": sid, "url": s["url"], "preview": r["text"][:1500], "cached": r["cached"], "via": r["via"]})
            else:
                s.update(status="failed", error=r["error"], archive_error=r.get("archive_error"))
                self.emit("fetch", f"Failed {s['domain']}", "progress", f"{r['error']} · archive: {r.get('archive_error')}", {"source": sid, "url": s["url"]})

        await asyncio.gather(*(one(sid) for sid in self.selected))
        failed = [sid for sid in self.selected if self.sources[sid]["status"] != "fetched"]
        backfilled = []
        for _ in range(2):   # replace failures with reserve pages (up to two rounds)
            if not failed or not self.backup:
                break
            batch = [self.backup.pop(0) for _ in range(min(len(failed), len(self.backup)))]
            for sid in batch:
                self.sources[sid]["status"] = "selected"; self.sources[sid]["backfill"] = True
            self.emit("fetch", f"Backfilling {len(batch)} failed page(s) with reserve sources", "progress", ", ".join(self.sources[b]["domain"] for b in batch), {"sources": batch})
            await asyncio.gather(*(one(sid) for sid in batch))
            self.selected += batch; backfilled += batch
            failed = [sid for sid in batch if self.sources[sid]["status"] != "fetched"]
        await ss.close()   # shut the headless browser if it was started
        useful = []
        for sid, t in self.docs.items():
            o = self.sources[sid]["origin"]
            if len(t) >= (150 if o == "community" else 800) and self._relevant(t):
                useful.append(sid)
                self.sources[sid]["useful"] = True
        ok = sum(self.sources[s]["status"] == "fetched" for s in self.selected)
        stats = {"pages_selected": len(self.selected), "pages_fetched": ok, "pages_failed": len(self.selected) - ok,
                 "via_archive": sum(1 for s in self.selected if str(self.sources[s].get("via", "")).startswith("web.archive")),
                 "backfilled": len(backfilled), "backfilled_ok": sum(self.sources[s]["status"] == "fetched" for s in backfilled),
                 "browser_tried": ss.browser_used["tried"], "browser_recovered": ss.browser_used["recovered"],
                 "pages_from_cache": ss.cache_hits["pages"], "pages_live": ss.live_calls["pages"],
                 "community_docs": sum(1 for s in self.sources.values() if s["origin"] == "community" and s["status"] == "fetched"),
                 "useful_docs": len(useful), "useful_by_type": dict(Counter(self.sources[s]["type"] for s in useful)),
                 "useful_domains": len({self.sources[s]["domain"] for s in useful})}
        self.result.setdefault("search_health", {})["fetch"] = stats
        self.result["search_health"]["search_cache_hits"] = ss.cache_hits["search"]
        self.result["search_health"]["search_live_calls"] = ss.live_calls["search"]
        return (f"{ok}/{len(self.selected)} pages read ({stats['pages_from_cache']} from cache, {stats['browser_recovered']}/{stats['browser_tried']} blocked pages recovered by headless browser, {stats['via_archive']} via Web Archive, {stats['backfilled_ok']} backfilled) + "
                f"{stats['community_docs']} community discussions → {len(useful)} useful documents from {stats['useful_domains']} domains",
                {"stats": stats, "sources": [{k: self.sources[s].get(k) for k in ("id", "url", "type", "status", "chars", "via", "cached", "error")}
                                             for s in self.selected]})

    def _texts(self):
        """(sid, text) for every usable document: fetched text, or search snippets when fetching was not possible."""
        for sid, s in self.sources.items():
            if sid in self.docs and self.docs[sid]:
                yield sid, self.docs[sid]
            elif s.get("snippets"):
                yield sid, "\n".join(s["snippets"])

    async def extract_claims(self):
        # a sentence belongs to a task when it shares ≥2 distinctive words with the task question (or its source was found for that task)
        task_words = {t["id"]: {w for w in X.norm(t["question"] + " " + t["q"]).split() if len(w) >= 4} for t in self.queries}
        per_src = Counter()
        self._claimed = getattr(self, "_claimed", set())
        before = len(self.claims)
        cands = []    # (sid, para, sentence, task ids) — classified in one GPU batch below
        for sid, text in self._texts():
            if sid in self._claimed:
                continue
            self._claimed.add(sid)
            src_tasks = self.sources[sid].get("tasks", [])
            seen = set()
            for para, sent in X.split_sentences(text):
                key = X.norm(sent)[:120]
                if key in seen:
                    continue
                seen.add(key)
                words = set(X.norm(sent).split())
                tids = [tid for tid, tw in task_words.items() if len(words & tw) >= 2] or src_tasks
                if not tids and not self._relevant(sent):
                    continue
                cands.append((sid, para, sent, tids))
        labels = await X.analyse_many([c[2] for c in cands], [self.sources[c[0]]["type"] for c in cands])
        for (sid, para, sent, tids), a in zip(cands, labels):
            if not a:
                continue
            self.add_claim(sent, sid, a, tids, {"para": para, "snippet": sid not in self.docs})
            per_src[sid] += 1
        kinds = Counter(c["kind"] for c in self.claims.values())
        epi = Counter(c["epistemic"] for c in self.claims.values())
        by_src = [{"source": sid, "domain": self.sources[sid]["domain"], "type": self.sources[sid]["type"], "claims": n,
                   "examples": [c["text"] for c in self.claims.values() if c["source"] == sid][:6]} for sid, n in per_src.most_common()]
        by_task = {t["id"]: sum(t["id"] in c["tasks"] for c in self.claims.values()) for t in self.queries}
        return (f"{len(self.claims) - before} new claims ({len(self.claims)} in ledger) — {', '.join(f'{v} {k}' for k, v in kinds.most_common())}; "
                f"epistemic: {', '.join(f'{v} {k}' for k, v in epi.most_common())}",
                {"per_source": by_src, "per_task": by_task})

    async def index(self):
        from ..store import db
        from ..ai_runtime import embed
        new, n_chunks, embedded = 0, 0, 0
        for sid, text in self.docs.items():
            s, h = self.sources[sid], hashlib.sha1(text.encode("utf8")).hexdigest()
            if not db.needs_index(s["url"], h):
                continue
            chunks = db.chunk(text)
            embs = await embed([f"search_document: {c}" for c in chunks]) if chunks else None
            db.put_document({"url": s["url"], "domain": s["domain"], "type": s["type"], "title": s.get("fetched_title") or s["title"],
                             "text": text, "text_hash": h, "via": s.get("via")}, chunks, embs)
            new += 1; n_chunks += len(chunks); embedded += len(chunks) if embs else 0
        db.put_claims(self.id, self.query, [{**c, "url": self.sources[c["source"]]["url"]} for c in self.claims.values()])
        st = db.stats()
        return (f"{new} new/changed documents → {n_chunks} chunks ({embedded} embedded); {len(self.claims)} claims stored. "
                f"Store now: {st['documents']} documents, {st['chunks']} chunks, {st['claims']} claims across {st['runs']} runs", st)

    # ---------- persistence ----------
    def snapshot(self):
        return {"id": self.id, "query": self.query, "status": self.status, "created": self.created, "events": self.events,
                "sources": self.sources, "claims": self.claims, "result": self.result,
                "docs": {k: v[:20000] for k, v in self.docs.items()}}

    def save(self):
        RUNS.mkdir(parents=True, exist_ok=True)
        (RUNS / f"{self.id}.json").write_text(json.dumps(self.snapshot(), default=list), encoding="utf8")
