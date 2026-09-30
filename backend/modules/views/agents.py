"""Agent roster + typed message bus, derived from a run's real events (nothing is simulated).

Every stage of the pipeline is owned by a named agent; every event becomes a typed message sender -> recipient.
    derive(snapshot) -> {"agents": [...], "messages": [...]}
"""
from collections import Counter

ROSTER = [  # id, name, role
    ("director", "Research Director", "Goal interview, hypotheses, planning, follow-up decisions"),
    ("market", "Market Agent", "Market size, growth, demand and trends"),
    ("competitor", "Competitor Agent", "Competitors, products and pricing"),
    ("customer", "Customer Agent", "Customers, needs, behaviour, willingness to pay"),
    ("regulation", "Regulation Agent", "Law, policy, compliance and operational risk"),
    ("judge", "Evidence Judge", "Freshness, independence, contradictions, weighing evidence"),
    ("challenger", "Adversarial Challenger", "Attacks the claims the verdict leans on"),
    ("verifier", "Verification Agent", "Re-researches challenged claims; checks every citation"),
    ("panel", "Trial Panel", "Advocate, challenger, witnesses and pre-mortem argue from the ledger"),
    ("court", "Evidence Court", "Per-claim hearing: prosecution, defence, ruling"),
    ("auditor", "Autopsy Auditors", "Second-order audit of the finished research"),
    ("synthesis", "Synthesis Agent", "Writes the decision report"),
]
SPECIALISTS = ("market", "competitor", "customer", "regulation")
OWNER = {"interview": "director", "hypotheses": "director", "plan": "director", "voi": "director", "complete": "director",
         "search": "specialists", "select": "specialists", "fetch": "specialists", "claims": "specialists",
         "ledger": "judge", "belief": "judge", "index": "judge", "challenge": "challenger", "trial": "panel",
         "report": "synthesis", "court": "court", "autopsy": "auditor"}
STATUS = {"running": "WORKING", "done": "COMPLETED", "failed": "ERROR", "waiting": "WAITING"}


def derive(snap: dict) -> dict:
    R = snap.get("result", {})
    tasks = {t["id"]: t for t in (R.get("plan") or {}).get("tasks", [])}
    agent_of_task = {tid: t.get("agent", "market") for tid, t in tasks.items()}
    agents = {aid: {"id": aid, "name": n, "role": r, "status": "IDLE", "current_task": None,
                    "sources": 0, "claims": 0, "challenges": 0, "messages": 0} for aid, n, r in ROSTER}
    for s in snap.get("sources", {}).values():
        for a in {agent_of_task.get(t) for t in s.get("tasks", [])} - {None}:
            agents[a]["sources"] += 1
    for c in snap.get("claims", {}).values():
        for a in {agent_of_task.get(t) for t in c.get("tasks", [])} - {None}:
            agents[a]["claims"] += 1
    agents["challenger"]["challenges"] = len(R.get("challenges", []))
    agents["judge"]["claims"] = len(snap.get("claims", {}))
    agents["judge"]["sources"] = len(snap.get("sources", {}))

    msgs = []

    def msg(ev, sender, recipient, mtype, summary, **refs):
        msgs.append({"id": f"m{len(msgs) + 1}", "t": ev["t"], "event": ev["i"], "sender": sender, "recipient": recipient,
                     "type": mtype, "summary": summary, **refs})

    for ev in snap.get("events", []):
        st, stage, d = ev["status"], ev["stage"], ev.get("data") or {}
        owner = OWNER.get(stage)
        targets = [a for a in SPECIALISTS if any(agent_of_task.get(t) == a for t in tasks)] if owner == "specialists" else [owner] if owner else []
        for a in targets:
            if st in STATUS:
                agents[a]["status"], agents[a]["current_task"] = STATUS[st], ev["title"] if st == "running" else agents[a]["current_task"]
        if stage == "await" and st == "waiting":
            msg(ev, "director", "user", "QUESTION", d.get("question", ev["title"]))
        elif stage == "interview" and st == "done":
            msg(ev, "director", "all", "RESEARCH_SCOPE_UPDATED", f"Goal confirmed after {len(d.get('qa', []))} answer(s)")
        elif stage == "hypotheses" and st == "done":
            for h in d.get("hypotheses", []):
                msg(ev, "director", "all", "HYPOTHESIS_CREATED", h["text"], hypothesis=h["id"])
        elif stage == "plan" and st == "done":
            for t in d.get("tasks", []):
                msg(ev, "director", t.get("agent", "market"), "TASK_ASSIGNED", t["question"], task=t["id"])
        elif stage == "search" and st == "progress" and d.get("query"):
            tid = next((t for t, x in tasks.items() if x.get("q") == d["query"]), None)
            msg(ev, agent_of_task.get(tid, "director"), "judge", "SEARCH", f"{d['query']} — {ev['summary']}", task=tid)
        elif stage == "fetch" and st == "progress" and d.get("source"):
            s = snap.get("sources", {}).get(d["source"], {})
            a = next((agent_of_task[t] for t in s.get("tasks", []) if t in agent_of_task), "director")
            ok = ev["title"].startswith("Read")
            msg(ev, a, "judge", "SOURCE_FOUND" if ok else "SOURCE_FAILED", ev["title"], source=d["source"])
        elif stage == "claims" and st == "done":
            per = Counter()
            for tid, n in (d.get("per_task") or {}).items():
                per[agent_of_task.get(tid, "market")] += n
            for a, n in per.items():
                msg(ev, a, "judge", "CLAIM_FOUND", f"{n} claims filed for {a} tasks")
        elif stage == "ledger" and st == "done":
            for c in d.get("conflicts", []):
                msg(ev, "judge", "all", "CONFLICT_DETECTED", f"{c['measure']} of {c['subject']}: {c['values']}", claims=[c["a"], c["b"]])
        elif stage == "belief" and st == "done":
            prev = {}
            for h in (d.get("result") or {}).get("hypotheses", []):
                kind = "HYPOTHESIS_SUPPORTED" if h["p"] >= 0.6 else "HYPOTHESIS_WEAKENED" if h["p"] <= 0.4 else "HYPOTHESIS_UNDECIDED"
                msg(ev, "judge", "director", kind, f"{h['id']} now {h['p']:.0%}", hypothesis=h["id"])
                prev[h["id"]] = h["p"]
        elif stage == "voi" and st == "done":
            for f in d.get("followups", []):
                msg(ev, "director", f.get("agent", "market"), "FOLLOW_UP_REQUIRED", f"{f['q']} (gap in {f.get('hypothesis')})", task=f["id"])
        elif stage == "challenge" and st == "progress" and d.get("claim"):
            owner_a = next((agent_of_task[t] for t in snap.get("claims", {}).get(d["claim"], {}).get("tasks", []) if t in agent_of_task), "judge")
            msg(ev, "challenger", owner_a, "CHALLENGE", d.get("argument", ""), claim=d["claim"], severity=d.get("severity"))
            msg(ev, "verifier", "judge", "VERIFICATION_RESULT", f"{d.get('status')}: {d.get('notes', '')}", claim=d["claim"])
        elif stage == "trial" and st == "done":
            for r in d.get("panel", []):
                for p in r.get("points", []):
                    msg(ev, "panel", "all", "COUNTER_ARGUMENT" if r["role"] in ("challenger", "premortem") else "ARGUMENT",
                        f"{r['title']}: {p['point']}", claims=p.get("cites", []))
        elif stage == "report" and st == "done" and d.get("verdict"):
            v = d["verdict"]
            msg(ev, "synthesis", "user", "FINAL_DECISION", f"{v.get('label')} — {v.get('p', 0):.0%}")
        elif stage == "court" and st == "done" and d.get("ruling"):
            msg(ev, "court", "all", "RULING", f"{d.get('claim')}: {d['ruling']}", claim=d.get("claim"))
        elif stage == "autopsy" and st == "done" and d.get("survival"):
            msg(ev, "auditor", "all", "AUDIT_VERDICT", f"{d['survival']} — {len(d.get('findings', []))} findings")
    for m in msgs:
        for a in (m["sender"], m["recipient"]):
            if a in agents:
                agents[a]["messages"] += 1
    if snap.get("status") in ("done", "failed"):
        for a in agents.values():
            if a["status"] == "WORKING":
                a["status"] = "COMPLETED"
    return {"agents": list(agents.values()), "messages": msgs}
