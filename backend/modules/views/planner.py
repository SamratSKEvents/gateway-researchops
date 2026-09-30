"""Planner state, derived from the run: task tree (initial decomposition + value-of-information follow-ups), open uncertainties,
plan versions per round, measured budget, coverage and saturation. Only measured numbers; nothing estimated for show."""


def derive(snap: dict) -> dict:
    R, events = snap.get("result", {}), snap.get("events", [])
    tasks = (R.get("plan") or {}).get("tasks", [])
    claims = snap.get("claims", {}).values()
    per_task = {t["id"]: sum(t["id"] in c.get("tasks", []) for c in claims) for t in tasks}
    voi_log = R.get("voi", [])
    gap_of = {(g["hypothesis"], g.get("round")): g for g in voi_log}
    hyp_text = {h["id"]: h["text"] for h in (R.get("hypotheses") or {}).get("hypotheses", [])}
    running = snap.get("status") == "running"
    rounds_done = sum(1 for e in events if e["stage"] == "belief" and e["status"] == "done")
    searching = any(e["stage"] in ("search", "fetch", "claims") and e["status"] == "running" for e in events[-3:])

    out_tasks = []
    for t in tasks:
        rnd = t.get("round", 0)
        n = per_task[t["id"]]
        status = "COMPLETED" if n else ("RUNNING" if running and rnd >= rounds_done and searching else
                                        "PLANNED" if running and rnd >= rounds_done else "BLOCKED")
        g = gap_of.get((t.get("hypothesis"), rnd))
        out_tasks.append({
            "id": t["id"], "title": t["question"], "query": t["q"], "agent": t.get("agent"), "agent_confidence": t.get("agent_confidence"),
            "phase": "Round 0 — broad decomposition" if rnd == 0 else f"Round {rnd} — follow-up on the highest-value gap",
            "parent": t.get("hypothesis"), "status": status, "claims": n,
            "priority": "HIGH" if g and g["voi"] >= 0.15 else "MEDIUM",
            "expected_information_gain": g["voi"] if g else None,
            "reason_for_creation": "initial decomposition of the question" if rnd == 0 else
                                   f"value of information: {hyp_text.get(t.get('hypothesis'), t.get('hypothesis'))} ({g['why'] if g else ''})",
            "reason_for_blocking": "searched, but no page yielded a claim for this task" if status == "BLOCKED" else None,
        })

    bel = (R.get("belief") or {}).get("result") or {}
    unc = []
    for h in bel.get("hypotheses", []):
        width = h["high"] - h["low"]
        settled = width < 0.25 or h["p"] >= 0.75 or h["p"] <= 0.25
        unc.append({"id": h["id"], "question": hyp_text.get(h["id"], h["id"]), "p": h["p"], "range": [h["low"], h["high"]],
                    "evidence_clusters": h.get("clusters"), "status": "RESOLVED" if settled else "OPEN",
                    "resolution_tasks": [t["id"] for t in tasks if t.get("hypothesis") == h["id"]]})
    for a in (R.get("belief") or {}).get("assumptions", []):
        unc.append({"id": a["id"], "question": a["text"], "p": a["p"], "range": None, "evidence_clusters": None,
                    "status": "ANSWERED" if a.get("answered") else "ASSUMED", "resolution_tasks": []})

    versions, added_so_far = [], set()
    for e in events:
        if e["status"] != "done":
            continue
        if e["stage"] == "plan":
            ids = [t["id"] for t in (e.get("data") or {}).get("tasks", []) if t.get("round", 0) == 0]
        elif e["stage"] == "voi":
            ids = [f["id"] for f in (e.get("data") or {}).get("followups", [])]
        else:
            continue
        new = [i for i in ids if i not in added_so_far]
        added_so_far |= set(new)
        versions.append({"version": f"PLAN v{len(versions) + 1}", "t": e["t"], "summary": e["summary"], "tasks_added": new,
                         "active_tasks": len(added_so_far)})

    last_voi = next((e for e in reversed(events) if e["stage"] == "voi" and e["status"] == "done"), None)
    saturated = bool(last_voi and not (last_voi.get("data") or {}).get("followups"))
    done = sum(t["status"] == "COMPLETED" for t in out_tasks)
    sh = R.get("search_health") or {}
    return {
        "question": snap.get("query"), "status": snap.get("status"), "round": rounds_done, "tasks": out_tasks, "uncertainties": unc,
        "versions": versions, "current_version": versions[-1]["version"] if versions else None,
        "budget": {"elapsed_s": events[-1]["t"] if events else 0, "rounds": rounds_done,
                   "searches": sum(1 for e in events if e["stage"] == "search" and e["status"] == "progress" and (e.get("data") or {}).get("query")),
                   "pages_read": sum(1 for e in events if e["stage"] == "fetch" and e["status"] == "progress" and e["title"].startswith("Read")),
                   "sources": len(snap.get("sources", {})), "claims": len(snap.get("claims", {})),
                   "search_cache_hits": sh.get("search_cache_hits"), "search_live_calls": sh.get("search_live_calls")},
        "coverage": round(done / len(out_tasks), 3) if out_tasks else 0,
        "confidence": round(1 - (bel["high"] - bel["low"]), 3) if bel else None,
        "saturated": saturated, "saturation_reason": last_voi["summary"] if saturated else None,
    }
