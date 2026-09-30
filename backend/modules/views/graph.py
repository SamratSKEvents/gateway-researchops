"""Evidence graph (nodes/edges) and categorised replay timeline, derived from a run snapshot."""

REPLAY_CAT = {"interview": "PLAN", "hypotheses": "PLAN", "plan": "PLAN", "voi": "PLAN", "await": "PLAN",
              "search": "DISCOVERY", "select": "DISCOVERY", "fetch": "DISCOVERY", "claims": "DISCOVERY", "index": "DISCOVERY",
              "ledger": "VERIFICATION", "belief": "VERIFICATION", "challenge": "CHALLENGE", "trial": "CHALLENGE",
              "court": "JUDICIAL", "report": "JUDICIAL", "autopsy": "JUDICIAL", "complete": "JUDICIAL"}


def graph(snap: dict, per_hyp: int = 8) -> dict:
    R, claims, sources = snap.get("result", {}), snap.get("claims", {}), snap.get("sources", {})
    nodes, edges, seen = [], [], set()

    def node(nid, kind, label, **kw):
        if nid not in seen:
            seen.add(nid); nodes.append({"id": nid, "type": kind, "label": label, **kw})

    node("question", "question", snap.get("query", ""))
    for h in (R.get("hypotheses") or {}).get("hypotheses", []):
        b = next((x for x in ((R.get("belief") or {}).get("result") or {}).get("hypotheses", []) if x["id"] == h["id"]), {})
        node(h["id"], "hypothesis", h["text"], p=b.get("p"), prior=h.get("prior"))
        edges.append({"source": h["id"], "target": "question", "type": "TESTS"})
    for a in (R.get("belief") or {}).get("assumptions", []):
        node(a["id"], "assumption", a["text"], p=a["p"], answered=a.get("answered"))
        edges.append({"source": a["id"], "target": a["hypothesis"], "type": "ASSUMED_BY"})
    per = {}
    for e in sorted((R.get("belief") or {}).get("evidence", []), key=lambda e: -e["strength"]):
        per[e["hypothesis"]] = per.get(e["hypothesis"], 0) + 1
        if per[e["hypothesis"]] > per_hyp or e["claim"] not in claims:
            continue
        c = claims[e["claim"]]
        node(c["id"], "claim", c["text"], status=c.get("status"), claim_type=c.get("claim_type"), freshness=c.get("freshness"))
        edges.append({"source": c["id"], "target": e["hypothesis"], "type": "SUPPORTS" if e["stance"] > 0 else "OPPOSES", "weight": e["strength"]})
        s = sources.get(c["source"], {})
        node(s.get("id", c["source"]), "source", s.get("domain", ""), url=s.get("url"), source_type=s.get("type"))
        edges.append({"source": c["source"], "target": c["id"], "type": "STATES"})
    for r in R.get("challenges", []):
        nid = f"ch:{r['claim']}"
        node(nid, "challenge", r["argument"], severity=r["severity"], status=r["status"])
        node(r["claim"], "claim", r["claim_text"], status=r["status"], claim_type=r["claim_type"])
        edges.append({"source": nid, "target": r["claim"], "type": "CHALLENGES"})
        for ev in r.get("evidence", []):
            if ev.get("claim_id"):
                node(ev["claim_id"], "claim", ev["quote"], status="VERIFICATION")
                edges.append({"source": ev["claim_id"], "target": r["claim"], "type": "CONFIRMS" if ev["entail"] >= ev["contradict"] else "CONTRADICTS"})
    for c in R.get("contradictions", []):
        if c["a"] in seen and c["b"] in seen:
            edges.append({"source": c["a"], "target": c["b"], "type": "CONFLICTS", "measure": c["measure"]})
    for cid, rec in (R.get("court") or {}).items():
        node(f"court:{cid}", "ruling", rec["ruling"], rationale=rec.get("rationale"))
        edges.append({"source": f"court:{cid}", "target": cid, "type": "RULES_ON"})
    return {"nodes": nodes, "edges": edges}


def replay(snap: dict) -> list[dict]:
    out = []
    for e in snap.get("events", []):
        if e["status"] == "progress" and e["stage"] in ("search", "fetch"):
            continue   # keep the timeline readable; details stay in the event log
        stage = "await" if e["stage"].startswith("await") else e["stage"]
        out.append({"step": len(out) + 1, "t": e["t"], "event": e["i"], "stage": stage, "category": REPLAY_CAT.get(stage, "DISCOVERY"),
                    "status": e["status"], "title": e["title"], "detail": e["summary"]})
    return out
