"""Deterministic report sections. Inputs are the run's own records; output is plain JSON for the UI and exports."""


def verdict_label(v, lo, hi):
    if lo > 0.5:
        return "favourable"
    if hi < 0.5:
        return "unfavourable"
    return "leaning favourable (uncertain)" if v >= 0.5 else "leaning unfavourable (uncertain)"


def gaps(hypotheses, belief, voi_log, conflicts):
    """What we could not verify: thin hypotheses, unresolved high-VOI gaps, conflicts."""
    by = {x["id"]: x for x in belief["hypotheses"]}
    out = []
    for h in hypotheses:
        b = by[h["id"]]
        if b["clusters"] == 0:
            out.append({"hypothesis": h["id"], "text": f"No usable evidence found for: \"{h['text']}\". Its probability is the starting assumption."})
        elif b["clusters"] < 2:
            out.append({"hypothesis": h["id"], "text": f"Only one independent evidence cluster for: \"{h['text']}\"."})
    for g in voi_log:
        if g.get("after_voi", 0) >= 0.15:
            out.append({"hypothesis": g["hypothesis"], "text": f"Still undecided after follow-up research ({g['why_after']})."})
    if conflicts:
        out.append({"hypothesis": None, "text": f"{len(conflicts)} numeric conflict(s) between sources remain unresolved (see Contradictions)."})
    return out


def assemble(decision, hypotheses, assumptions, belief, cruxes, conflicts, voi_log, prose, rulings, claims, sources):
    """claims: {id: claim}, sources: {id: source}; prose items carry cites; rulings: {item_id: {ruling}}."""
    def keep(items):
        return [dict(it, ruling=rulings.get(it["id"], {}).get("ruling", "unchecked"), ruling_reason=rulings.get(it["id"], {}).get("reason", ""))
                for it in items if rulings.get(it["id"], {}).get("ruling") != "unsupported"]

    struck = [dict(it, section=sec, reason=rulings[it["id"]]["reason"]) for sec in ("summary", "must_do", "must_not")
              for it in prose.get(sec, []) if rulings.get(it["id"], {}).get("ruling") == "unsupported"]
    body = {sec: keep(prose.get(sec, [])) for sec in ("summary", "must_do", "must_not")}
    cited = {c for sec in body.values() for it in sec for c in it["cites"]} | {c["id"] for c in cruxes if c["kind"] == "evidence"} \
        | {x for c in conflicts for x in (c["a"], c["b"])}
    used = {}
    for cid in sorted(cited, key=lambda c: int(c[1:]) if c[1:].isdigit() else 0):
        if cid in claims:
            s = sources[claims[cid]["source"]]
            used.setdefault(s["id"], {"id": s["id"], "url": s["url"], "title": s.get("fetched_title") or s.get("title"), "domain": s["domain"],
                                      "type": s["type_label"], "claims": []})["claims"].append(cid)
    by = {x["id"]: x for x in belief["hypotheses"]}
    checked = [r for r in rulings.values() if r["ruling"] != "unchecked"]
    return {
        "decision": decision,
        "verdict": {"p": belief["verdict"], "low": belief["low"], "high": belief["high"],
                    "label": verdict_label(belief["verdict"], belief["low"], belief["high"])},
        "hypotheses": [{**h, **{k: by[h["id"]][k] for k in ("p", "low", "high", "clusters", "for", "against")}} for h in hypotheses],
        "assumptions": assumptions,
        **body,
        "cruxes": cruxes,
        "contradictions": conflicts,
        "gaps": gaps(hypotheses, belief, voi_log, conflicts),
        "struck": struck,
        "verification": {"statements": len(rulings), "supported": sum(r["ruling"] == "supported" for r in checked),
                         "partial": sum(r["ruling"] == "partial" for r in checked),
                         "struck": sum(r["ruling"] == "unsupported" for r in checked), "unchecked": len(rulings) - len(checked)},
        "sources": list(used.values()),
    }
