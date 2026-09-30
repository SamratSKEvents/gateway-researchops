"""Research Autopsy: an independent, second-order audit of a FINISHED run. It tries to break the conclusion.

    await run(snap, llm=chat_json) -> {"findings", "survival", "survival_reasoning", "integrity", "what_would_change", "followups", "auditors"}

Computed auditors read the run's own records (freshness, independence clusters, source types, verifier rulings, challenge
outcomes, belief ranges, cruxes). Meaning is judged by the zero-shot classifier (e.g. "a statistic without its sample size"),
never by regexes. Qualitative auditors (logic, alternative hypothesis, methodology, completeness) are one LLM call that may only
cite claims in the run. The Red Team Director turns the findings into a survival verdict with a transparent score.
"""
from collections import Counter
from .. import classify
from ..ai_runtime import chat_json
from ..ledger import cite_id

AUDITORS = {
    "temporal": "Temporal Auditor", "source": "Source Quality Auditor", "evidence": "Evidence Auditor",
    "contradiction": "Contradiction Auditor", "data": "Data Quality Auditor", "assumption": "Assumption Auditor",
    "bias": "Bias Auditor", "conclusion": "Conclusion Auditor", "completeness": "Completeness Auditor",
    "logic": "Logic Auditor", "alternative": "Alternative Hypothesis Auditor", "methodology": "Methodology Auditor",
    "director": "Red Team Director",
}
SEV_W = {"CRITICAL": 5, "HIGH": 3, "MEDIUM": 1.5, "LOW": 0.5}
STAT = {"with_n": "This text reports a statistic and says how many people or items it was measured on.",
        "no_n": "This text reports a percentage or statistic without saying how many were measured or who measured it.",
        "none": "This text contains no statistic or percentage."}
LLM_SCHEMA = {"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array", "maxItems": 6, "items": {"type": "object",
    "required": ["auditor", "title", "description", "why_it_matters", "severity", "claims", "recommended_action", "needs_research"],
    "properties": {"auditor": {"enum": ["logic", "alternative", "methodology", "completeness"]}, "title": {"type": "string", "maxLength": 120},
                   "description": {"type": "string", "maxLength": 400}, "why_it_matters": {"type": "string", "maxLength": 240},
                   "severity": {"enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]}, "claims": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                   "recommended_action": {"type": "string", "maxLength": 200}, "needs_research": {"type": "boolean"}}}}}}
LLM_SYSTEM = ("You are a red-team audit panel reviewing a finished business research run. Find what could break its conclusion: "
              "logic auditor (leaps from correlation to causation, from pain to purchase, from market size to revenue); alternative "
              "hypothesis auditor (a competing explanation that fits the same evidence); methodology auditor (sampling, missing "
              "comparison groups, scope mismatch between evidence and decision); completeness auditor (a decision-relevant dimension "
              "nobody researched). Only report real problems visible in the material; cite claim ids from the evidence list; no "
              "invented facts. Up to 6 findings.")


def _f(findings, auditor, title, severity, description, why, claims=(), action="", research=False, basis=""):
    findings.append({"id": f"F{len(findings) + 1:02d}", "auditor": auditor, "auditor_name": AUDITORS[auditor], "title": title,
                     "severity": severity, "description": description, "why_it_matters": why, "claims": list(claims),
                     "recommended_action": action, "needs_research": research, "basis": basis or "computed from run records"})


def _used_claims(R):
    rep = R.get("report") or {}
    ids = {c for sec in ("summary", "must_do", "must_not") for it in rep.get(sec, []) for c in it.get("cites", [])}
    ids |= {x for x in (R.get("trial") or {}).get("exhibits", [])}
    return ids


async def run(snap: dict, llm=chat_json) -> dict:
    R, claims, sources = snap["result"], snap["claims"], snap["sources"]
    rep, bel = R.get("report") or {}, R.get("belief") or {}
    used = [cid for cid in _used_claims(R) if cid in claims] or list(claims)[:40]
    F = []

    # temporal
    stale = [c for c in used if claims[c].get("freshness", 1) < 0.5]
    crux_claims = {c.get("claim") for c in bel.get("cruxes", []) if c.get("kind") == "evidence"}
    if stale:
        sev = "HIGH" if set(stale) & crux_claims else "MEDIUM" if len(stale) >= 3 else "LOW"
        _f(F, "temporal", f"{len(stale)} cited claim(s) are stale for their kind", sev,
           "Claims the conclusion relies on are old relative to how fast their kind of fact changes (prices, competitors).",
           "Stale figures can reverse the decision if the market moved.", stale[:6], "Re-check these figures against current sources.", True)

    # source independence and type concentration
    doms = Counter(sources[claims[c]["source"]]["domain"] for c in used)
    types = Counter(sources[claims[c]["source"]]["type"] for c in used)
    if used and doms:
        dom, n = doms.most_common(1)[0]
        if n / len(used) >= 0.35:
            _f(F, "source", f"{n / len(used):.0%} of cited evidence comes from one domain ({dom})", "HIGH" if n / len(used) >= 0.5 else "MEDIUM",
               "The conclusion leans on a single publisher.", "One publisher's error or bias propagates to the verdict.",
               [c for c in used if sources[claims[c]["source"]]["domain"] == dom][:6], "Find independent publishers for the same facts.", True)
    interested = sum(v for k, v in types.items() if k in ("commercial", "company"))
    if used and interested / len(used) >= 0.4:
        _f(F, "bias", f"{interested / len(used):.0%} of cited evidence is from vendors or commercial listings", "MEDIUM",
           "Interested parties describe their own products favourably.", "Vendor claims overstate demand and quality.",
           [c for c in used if sources[claims[c]["source"]]["type"] in ("commercial", "company")][:6],
           "Replace with independent reporting or data.", True)
    copies = [c for c in used if claims[c].get("cluster_domains", 1) > 1 and Counter(x.get("cluster") for x in claims.values())[claims[c].get("cluster")] > 2]
    if copies:
        _f(F, "source", f"{len(copies)} cited claim(s) are repeated across sites (syndicated copies)", "LOW",
           "Several pages carry the same sentence; they were counted once, but readers may see them as independent confirmation.",
           "Apparent consensus may be one original source.", copies[:6], "Trace each to its original publisher.")

    # evidence alignment (citation verifier) and challenge outcomes
    v = rep.get("verification") or {}
    if v.get("statements") and (v.get("struck", 0) + v.get("partial", 0)) / v["statements"] >= 0.3:
        _f(F, "evidence", f"{v.get('struck', 0)} struck and {v.get('partial', 0)} partial of {v['statements']} cited statements", "HIGH",
           "The entailment verifier found many report or trial statements not fully supported by their quotes.",
           "Unsupported statements inflate confidence in the conclusion.", [], "Rewrite or drop the struck statements.")
    ch = R.get("challenges", [])
    bad = [r for r in ch if r["status"] in ("CONTRADICTED", "OUTDATED")]
    if bad:
        _f(F, "contradiction", f"{len(bad)} challenged claim(s) were contradicted by independent sources", "HIGH" if len(bad) >= 2 else "MEDIUM",
           "; ".join(f"{r['claim']}: {r['notes']}" for r in bad[:3]), "Contradicted claims were down-weighted but still shape the narrative.",
           [r["claim"] for r in bad], "Resolve each contradiction with a primary source.", True)
    conf = R.get("contradictions", [])
    if conf:
        _f(F, "contradiction", f"{len(conf)} numeric conflict(s) between sources are unresolved", "MEDIUM" if len(conf) < 4 else "HIGH",
           "; ".join(f"{c['measure']} of {c['subject']}: {c['values']}" for c in conf[:3]), "Conflicting numbers make projections unreliable.",
           [x for c in conf[:3] for x in (c["a"], c["b"])], "Find which figure is current and from whom.", True)

    # data quality (classifier)
    texts = [claims[c]["text"] for c in used]
    stat = await classify.best(texts, STAT) if texts else []
    no_n = [c for c, (lab, p) in zip(used, stat) if lab == "no_n" and p >= 0.5]
    if no_n:
        _f(F, "data", f"{len(no_n)} statistic(s) are cited without a sample size or measurer", "MEDIUM" if len(no_n) >= 2 else "LOW",
           "Percentages and figures appear without who measured them or on how many.", "Significance cannot be judged; small samples mislead.",
           no_n[:6], "Find the underlying study or mark the figure as unverified.", False, "zero-shot classifier over cited claims")

    # opinion-heavy evidence (classifier-typed claims from the challenge stage, else classify now)
    typed = [r.get("claim_type") for r in ch]
    if typed and typed.count("OPINION") / len(typed) >= 0.4:
        _f(F, "bias", f"{typed.count('OPINION')}/{len(typed)} of the claims the verdict leans on are opinions", "MEDIUM",
           "The strongest evidence is personal opinion rather than measured fact.", "Anecdotes do not generalise to a market.",
           [r["claim"] for r in ch if r.get("claim_type") == "OPINION"], "Back these with measured data.", True, "zero-shot classifier")

    # assumptions and conclusion overreach
    for c in bel.get("cruxes", []):
        if c.get("kind") == "assumption" and c.get("flips") and not any(a.get("answered") for a in bel.get("assumptions", []) if a["id"] == c["id"]):
            _f(F, "assumption", f"Unverified assumption can flip the verdict: {c['text'][:90]}", "CRITICAL",
               f"Reversing it moves the verdict to {c['verdict_without']:.0%}.", "The decision rests on something nobody checked.",
               [], "Ask the decision-maker or find evidence for this assumption.", True)
    vd = rep.get("verdict") or {}
    if vd and (vd.get("high", 0) - vd.get("low", 0)) >= 0.35 and vd.get("label") in ("favourable", "unfavourable"):
        _f(F, "conclusion", "Decisive label with a wide uncertainty range", "HIGH",
           f"Verdict is labelled {vd['label']} but ranges {vd['low']:.0%}-{vd['high']:.0%}.", "The report overstates how settled the decision is.",
           [], "Present the verdict as conditional until the range narrows.")
    for h in rep.get("hypotheses", []):
        if h.get("clusters", 0) < 2:
            _f(F, "completeness", f"Hypothesis {h['id']} rests on {h.get('clusters', 0)} independent evidence cluster(s)", "MEDIUM",
               h["text"], "Its probability is mostly the starting assumption.", [], "Research this hypothesis directly.", True)

    # qualitative LLM auditors
    ev_list = "\n".join(f"[{c}] {claims[c]['text']}" for c in used[:40])
    ctx = (f"DECISION: {rep.get('decision', snap.get('query'))}\nVERDICT: {vd.get('label')} {vd.get('p', 0):.0%}\n"
           f"SUMMARY: " + " ".join(it["text"] for it in rep.get("summary", [])) + f"\n\nEVIDENCE:\n{ev_list}")
    try:
        j = await llm("autopsy.panel", LLM_SYSTEM, ctx, LLM_SCHEMA, 1600)
        for x in (j or {}).get("findings", []):
            cites = [cite_id(c) for c in x.get("claims", [])]
            _f(F, x["auditor"], x["title"], x["severity"], x["description"], x["why_it_matters"], [c for c in cites if c in claims],
               x["recommended_action"], bool(x["needs_research"]), "LLM auditor, citations checked against the run")
    except Exception as e:
        _f(F, "director", "Qualitative auditors unavailable", "LOW", f"{type(e).__name__}", "Logic and methodology were not audited.", [])

    # red team director
    score = sum(SEV_W[f["severity"]] for f in F)
    crit = sum(f["severity"] == "CRITICAL" for f in F)
    survival = "SURVIVES" if score < 4 else "SURVIVES WITH CAVEATS" if score < 10 else "WEAKENED" if score < 18 else "FAILS"
    if crit and survival in ("SURVIVES", "SURVIVES WITH CAVEATS"):
        survival = "WEAKENED"
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    F.sort(key=lambda f: order[f["severity"]])
    change = [{"kind": c["kind"], "text": c.get("text") or claims.get(c.get("claim"), {}).get("text", ""), "verdict_without": c["verdict_without"],
               "flips": c["flips"]} for c in bel.get("cruxes", [])] + \
             [{"kind": "finding", "text": f["title"], "finding": f["id"]} for f in F if f["severity"] in ("CRITICAL", "HIGH")]
    followups = [{"id": f"AT{i + 1}", "question": f["recommended_action"], "reason": f["title"], "finding": f["id"], "claims": f["claims"],
                  "priority": order[f["severity"]] + 1, "suggested_agent": {"temporal": "verifier", "source": "verifier", "data": "verifier",
                  "contradiction": "verifier", "assumption": "director"}.get(f["auditor"], "market")}
                 for i, f in enumerate(x for x in F if x["needs_research"])]
    return {"findings": F, "survival": survival,
            "survival_reasoning": f"Severity score {score:g} ({', '.join(f'{v} {k.lower()}' for k, v in Counter(f['severity'] for f in F).most_common()) or 'no findings'}); "
                                  "thresholds 4 / 10 / 18; any critical finding caps the verdict at WEAKENED.",
            "integrity": dict(Counter(f["severity"] for f in F)), "what_would_change": change, "followups": followups,
            "auditors": [{"id": k, "name": n, "findings": sum(f["auditor"] == k for f in F)} for k, n in AUDITORS.items()],
            "audited": {"claims": len(used), "sources": len({claims[c]["source"] for c in used})}}
