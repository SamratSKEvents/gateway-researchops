"""Research Director: owns a run end to end.
  hearing   goal interview (blocks until the user answers) -> hypotheses (blocks until the user confirms/edits)
  round 0   broad: planned tasks -> search -> select -> fetch -> claims -> ledger -> stance -> belief
  rounds 1+ deep: VOI picks the highest-value gap -> targeted follow-up queries (and asks the user only if it changes the verdict)
  trial     advocate / challenger / witnesses / pre-mortem argue from the ledger; verifier rules on every statement
  report    cited prose + deterministic verdict, cruxes, contradictions, gaps, sources
A new goal mid-run re-builds the hypotheses and re-scores the existing ledger without re-fetching."""
import asyncio
from collections import Counter
from .pipeline import Run
from . import _llm as llm
from .. import goals, ledger as L, belief as B, voi, trial, report

MAX_ROUNDS = 2            # deep follow-up rounds after the broad one
FOLLOWUP_BUDGET = 10      # pages read per follow-up round
USER_QUESTION_TIMEOUT = 180
TRIAL_EXHIBITS = 36


class Director(Run):
    def __init__(self, query):
        super().__init__(query)
        self.qa, self.goal, self.hyp = [], None, None
        self.labels, self.stance_done, self.asked, self.voi_log = [], set(), set(), []
        self.pending, self._reply, self.goal_change = None, None, None
        self.clusters, self.conflicts = {}, []
        self._followups = []

    # ---------- user in the loop ----------
    async def ask(self, kind, payload, timeout=None):
        """Publish a question and wait for /reply. timeout=None blocks until the user answers."""
        self._reply = asyncio.get_running_loop().create_future()
        self.pending = {"kind": kind, **payload}
        self.emit("await", payload.get("title", "Waiting for your input"), "waiting", payload.get("question", ""), self.pending)
        try:
            return await asyncio.wait_for(self._reply, timeout)
        except asyncio.TimeoutError:
            self.emit("await", "No answer in time — continuing with the stated assumption", "done", "")
            return None
        finally:
            self.pending, self._reply = None, None

    def reply(self, answer) -> bool:
        if self._reply and not self._reply.done():
            self._reply.set_result(answer)
            return True
        return False

    def change_goal(self, text):
        self.goal_change = text.strip()

    # ---------- orchestration ----------
    async def execute(self):
        from ..ai_runtime import info as ai_info
        self.result["ai"] = {**ai_info(), "note": "model used for every LLM step in this run"}
        try:
            await self.stage("interview", "Goal interview", self.interview, required=True)
            await self.stage("hypotheses", "Hypotheses & assumptions", self.hypotheses, required=True)
            await self.stage("plan", "Break the question into research tasks", self.plan, required=True)
            await self.research_round(0, self.queries, community=True, budget=None)
            for r in range(1, MAX_ROUNDS + 1):
                if not await self.stage("voi", f"Value of information — round {r}", lambda r=r: self.voi_round(r)):
                    break
                if not self._followups:
                    break
                await self.research_round(r, self._followups, community=False, budget=FOLLOWUP_BUDGET)
            await self.stage("index", "Store documents & claims in the global datastore", self.index)
            await self.stage("trial", "Trial: advocate, challenger, witnesses, pre-mortem", self.trial)
            await self.stage("report", "Verify citations & write the decision report", self.write_report)
            self.status = "done"
            v = self.result["report"]["verdict"]
            self.emit("complete", "Research completed", "done", f"{v['label']} — {v['p']:.0%} ({v['low']:.0%}–{v['high']:.0%})")
        except Exception as e:
            self.status = "failed"
            self.emit("complete", "Research stopped", "failed", str(e))
        self.save()

    async def research_round(self, r, queries, community, budget):
        tag = "broad" if r == 0 else "deep"
        await self.stage("search", f"Round {r} ({tag}) — search", lambda: self.search(queries, community), required=(r == 0))
        await self.stage("select", f"Round {r} — select sources", lambda: self.select(budget) if budget else self.select())
        await self.stage("fetch", f"Round {r} — read sources", self.fetch)
        await self.stage("claims", f"Round {r} — extract claims", self.extract_claims)
        await self.stage("ledger", f"Round {r} — ledger: freshness, independence, contradictions", self.update_ledger)
        await self.stage("belief", f"Round {r} — weigh evidence against hypotheses", self.update_belief)

    # ---------- hearing ----------
    async def interview(self):
        while True:
            step = await goals.next_step(self.query, self.qa)
            if step["ready"]:
                break
            ans = await self.ask("interview", {"title": "Goal interview", "question": step["question"], "missing": step["missing"],
                                               "hint": "Answer in your own words, or reply 'skip' to proceed with stated assumptions."})
            self.qa.append({"q": step["question"], "a": str(ans or "skip")})
        self.goal = step["goal"]
        self.result["goal"] = {"goal": self.goal, "qa": self.qa, "open_points": step["missing"], "how": step["how"]}
        return f"goal confirmed after {len(self.qa)} question(s): {self.goal[:160]}", self.result["goal"]

    async def hypotheses(self):
        h = await goals.build(self.query, self.goal)
        ans = await self.ask("hypotheses", {"title": "Confirm hypotheses", "question": "Edit the hypotheses or their starting "
                                            "likelihoods, then confirm.", "decision": h["decision"], "hypotheses": h["hypotheses"],
                                            "assumptions": h["assumptions"]})
        if isinstance(ans, dict):   # user edits: text / prior / weight per hypothesis id; removed ids dropped
            edits = {x.get("id"): x for x in ans.get("hypotheses", [])}
            if edits:
                h["hypotheses"] = [{**x, **{k: edits[x["id"]][k] for k in ("text", "prior", "weight") if k in edits[x["id"]]}}
                                   for x in h["hypotheses"] if x["id"] in edits]
                keep = {x["id"] for x in h["hypotheses"]}
                h["assumptions"] = [a for a in h["assumptions"] if a["hypothesis"] in keep]
        self.hyp = h
        self._publish_hypotheses()
        return f"{len(h['hypotheses'])} hypotheses, {len(h['assumptions'])} inferred assumptions ({h['how']})", h

    def _publish_hypotheses(self):
        self.result["hypotheses"] = {k: self.hyp[k] for k in ("decision", "hypotheses", "assumptions", "how")}

    # ---------- ledger & belief ----------
    async def update_ledger(self):
        doc_years = {sid: L.doc_year(t) for sid, t in self.docs.items()}
        for c in self.claims.values():
            if "freshness" not in c:
                c["year"] = L.claim_year(c["text"], doc_years.get(c["source"]))
                c["freshness"] = L.freshness(c["kind"], c["year"], bool(c.get("prices")))
        items = [(cid, c["text"]) for cid, c in self.claims.items()]
        self.clusters = await asyncio.to_thread(L.cluster, items)
        domains = {}
        for cid, k in self.clusters.items():
            domains.setdefault(k, set()).add(self.sources[self.claims[cid]["source"]]["domain"])
        for cid, c in self.claims.items():
            c["cluster"], c["cluster_domains"] = self.clusters[cid], len(domains[self.clusters[cid]])
        self.conflicts = L.find_conflicts([{"id": c["id"], "text": c["text"], "cluster": c["cluster"], "source": c["source"]}
                                           for c in self.claims.values() if c["kind"] != "opinion"])
        n_clusters = len(set(self.clusters.values()))
        copies = sum(1 for k, n in Counter(self.clusters.values()).items() if n > 1)
        stale = sum(c["freshness"] < 0.5 for c in self.claims.values())
        self.result["ledger"] = {"claims": len(self.claims), "clusters": n_clusters, "multi_copy_clusters": copies,
                                 "stale_claims": stale, "undated_claims": sum(c["year"] is None for c in self.claims.values())}
        self.result["contradictions"] = self.conflicts
        return (f"{len(self.claims)} claims -> {n_clusters} independent clusters ({copies} with repeated copies); "
                f"{stale} stale; {len(self.conflicts)} numeric contradictions", {**self.result["ledger"], "conflicts": self.conflicts})

    def evidence(self):
        out = []
        for lab in self.labels:
            c = self.claims[lab["claim"]]
            out.append({**lab, "cluster": c["cluster"], "reliability": self.sources[c["source"]]["authority"],
                        "freshness": c["freshness"], "domains": c["cluster_domains"]})
        return out

    async def update_belief(self):
        if self.goal_change:
            await self._apply_goal_change()
        cands = [{"id": c["id"], "text": c["text"], "cluster": c["cluster"], "authority": self.sources[c["source"]]["authority"]}
                 for c in self.claims.values()]
        new, self.stance_done, failed = await B.stance.label(self.hyp["hypotheses"], cands, self.stance_done)
        self.labels += new
        self._recompute()
        b = self.result["belief"]["result"]
        return (f"{len(new)} new evidence labels ({failed} batches failed); verdict {b['verdict']:.0%} ({b['low']:.0%}–{b['high']:.0%}); "
                + "; ".join(f"{h['id']} {h['p']:.0%}" for h in b["hypotheses"]), self.result["belief"])

    def _recompute(self):
        H, A, E = self.hyp["hypotheses"], self.hyp["assumptions"], self.evidence()
        res = B.compute(H, A, E)
        hist = (self.result.get("belief") or {}).get("history", [])
        self.result["belief"] = {"hypotheses": H, "assumptions": A, "evidence": E, "result": res,
                                 "cruxes": B.cruxes(H, A, E), "history": hist + [{"t": self.events[-1]["t"] if self.events else 0,
                                                                                    "verdict": res["verdict"]}]}

    async def _apply_goal_change(self):
        new_goal, self.goal_change = self.goal_change, None
        self.goal = f"{self.goal}\nUPDATED GOAL: {new_goal}"
        self.hyp = await goals.build(self.query, self.goal)
        self.labels, self.stance_done, self.asked = [], set(), set()
        self._publish_hypotheses()
        self.result.setdefault("goal", {})["changes"] = self.result.get("goal", {}).get("changes", []) + [new_goal]
        self.emit("hypotheses", "Goal changed — hypotheses rebuilt, existing evidence re-scored (no re-fetch)", "done", new_goal, self.hyp)

    # ---------- value of information ----------
    async def voi_round(self, r):
        if self.goal_change:
            await self.update_belief()
        H, A, E = self.hyp["hypotheses"], self.hyp["assumptions"], self.evidence()
        belief = B.compute(H, A, E)
        for g in self.voi_log:     # how did earlier gaps end up?
            if "after_voi" not in g:
                g2 = next((x for x in voi.rank_gaps(H, belief, 0) if x["hypothesis"] == g["hypothesis"]), None)
                g["after_voi"], g["why_after"] = (g2["voi"], g2["why"]) if g2 else (0, "")
        q = voi.question_for_user(H, A, E, self.asked)
        if q:
            self.asked.add(q["assumption"])
            ans = await self.ask("assumption", {"title": "One question that changes the verdict", **q,
                                                "hint": "Reply with a likelihood 0-100, or words like 'yes' / 'no' / 'unsure'."},
                                 USER_QUESTION_TIMEOUT)
            p = _to_prob(ans)
            if p is not None:
                for a in A:
                    if a["id"] == q["assumption"]:
                        a["p"] = a["p0"] = p     # the user's answer becomes the new baseline
                        a["answered"] = str(ans)
                self._recompute()
        gaps = voi.rank_gaps(H, B.compute(H, A, E))[:2]
        self._followups = []
        if not gaps:
            return "no gap worth another round: every important hypothesis is settled or well evidenced", {"gaps": []}
        ents = [w for w, _ in Counter(w for c in self.claims.values() for w in L.entities(c["text"])).most_common(15)]
        tried = [x["q"] for x in self.queries]
        byid = {h["id"]: h for h in H}
        for g in gaps:
            for qtext in await voi.followup_queries(byid[g["hypothesis"]], tried, ents):
                self._followups.append({"id": f"f{len(self.queries) + len(self._followups) + 1}", "question": byid[g["hypothesis"]]["text"],
                                        "q": qtext, "hypothesis": g["hypothesis"], "round": r})
            self.voi_log.append({**g, "round": r})
        self.queries += self._followups
        self.result["plan"]["tasks"] = self.queries
        self.result["voi"] = self.voi_log
        return (f"researching {', '.join(g['hypothesis'] for g in gaps)} deeper with {len(self._followups)} follow-up queries"
                + (f"; asked the user about {q['assumption']}" if q else ""), {"gaps": gaps, "followups": self._followups, "question": q})

    # ---------- trial & report ----------
    def _exhibits(self):
        E = self.evidence()
        best = sorted(E, key=lambda e: -(e["strength"] * e["reliability"] * e["freshness"]))
        chosen, seen = [], set()
        for e in best:
            if e["cluster"] not in seen:
                seen.add(e["cluster"]); chosen.append(e)
        chosen = chosen[:TRIAL_EXHIBITS]
        ids = {e["claim"] for e in chosen} | {x for c in self.conflicts[:6] for x in (c["a"], c["b"])}
        notes = {}
        for e in E:
            if e["claim"] in ids:
                notes.setdefault(e["claim"], []).append(f"{'supports' if e['stance'] > 0 else 'opposes'} {e['hypothesis']}")
        out = []
        for cid in ids:
            c, s = self.claims[cid], self.sources[self.claims[cid]["source"]]
            out.append({"id": cid, "text": c["text"], "source_type": s["type_label"], "domain": s["domain"], "year": c.get("year"),
                        "stance_note": ", ".join(notes.get(cid, []))})
        return out

    def _verdict_line(self):
        b = self.result["belief"]["result"]
        hs = {h["id"]: h for h in self.hyp["hypotheses"]}
        return (f"{b['verdict']:.0%} favourable (range {b['low']:.0%}-{b['high']:.0%}). "
                + " ".join(f"{h['id']} \"{hs[h['id']]['text']}\": {h['p']:.0%}." for h in b["hypotheses"]))

    async def trial(self):
        self.exhibits = self._exhibits()
        if not self.exhibits:
            raise RuntimeError("no labelled evidence to argue with")
        panel = await trial.hold(self.hyp["decision"], self._verdict_line(), self.exhibits)
        self.result["trial"] = {"panel": panel, "exhibits": [x["id"] for x in self.exhibits]}
        n = sum(len(r["points"]) for r in panel)
        return f"{n} arguments from {sum(bool(r['points']) for r in panel)}/{len(panel)} speakers", self.result["trial"]

    async def write_report(self):
        panel = (self.result.get("trial") or {}).get("panel", [])
        hearing = "\n".join(f"{r['title']}: {p['point']} {p['cites']}" for r in panel for p in r["points"])
        conflicts = "\n".join(f"- {c['measure']} of {c['subject']}: [{c['a']}] vs [{c['b']}]" for c in self.conflicts[:10])
        cx = "\n".join(f"- {c['kind']} {c['id']}: {c.get('claim') or c.get('text')} (verdict without it: {c['verdict_without']:.0%})"
                       for c in self.result["belief"]["cruxes"])
        ex = "\n".join(f"[{x['id']}] ({x['source_type']}, {x['domain']}, {x['year'] or 'undated'}) {x['text']}" for x in self.exhibits)
        ctx = (f"DECISION: {self.hyp['decision']}\nUSER GOAL: {self.goal}\nESTIMATE: {self._verdict_line()}\n\nEVIDENCE:\n{ex}\n\n"
               f"HEARING RECORD:\n{hearing or 'none'}\n\nCONTRADICTIONS:\n{conflicts or 'none'}\n\nCRUXES:\n{cx or 'none'}")
        valid = set(self.claims)
        try:
            prose = await report.draft(ctx, valid)
        except Exception as e:
            prose = {"summary": [], "must_do": [], "must_not": []}
            self.emit("report", "Report writer unavailable — deterministic sections only", "progress", f"{type(e).__name__}: {e}")
        statements = [it for sec in prose.values() for it in sec]
        statements += [{"id": f"{r['role']}.{i}", "text": p["point"], "cites": p["cites"]} for r in panel for i, p in enumerate(r["points"]) if p["cites"]]
        rulings = await trial.verify(statements, {cid: c["text"] for cid, c in self.claims.items()})
        for r in panel:
            for i, p in enumerate(r["points"]):
                p["ruling"] = rulings.get(f"{r['role']}.{i}", {"ruling": "no citation", "reason": ""})
        b = self.result["belief"]
        self.result["report"] = report.assemble(self.hyp["decision"], self.hyp["hypotheses"], self.hyp["assumptions"], b["result"],
                                                b["cruxes"], self.conflicts, self.voi_log, prose, rulings, self.claims, self.sources)
        self.result["report"]["model"] = llm.MODEL
        v = self.result["report"]["verification"]
        return (f"verdict {self.result['report']['verdict']['label']}; verifier: {v['supported']} supported, {v['partial']} partial, "
                f"{v['struck']} struck, {v['unchecked']} unchecked of {v['statements']} statements", self.result["report"])

    def snapshot(self):
        return {**super().snapshot(), "pending": self.pending}


def _to_prob(ans):
    if ans is None:
        return None
    s = str(ans).strip().lower().rstrip("%")
    try:
        v = float(s)
        return min(max(v / 100 if v > 1 else v, 0.05), 0.95)
    except ValueError:
        return {"yes": 0.85, "true": 0.85, "mostly": 0.7, "likely": 0.7, "unsure": None, "maybe": 0.5,
                "unlikely": 0.3, "no": 0.15, "false": 0.15}.get(s)
