"""What-if / counterfactual lab over a finished (or live) run's belief state. No new research; the belief engine does the math.

    fork(belief, changes) -> {"baseline", "result", "diff", "cruxes", "applied"}
        changes = {"assumptions": {id: p}, "priors": {hypothesis_id: prior}, "drop_claims": [claim ids],
                   "extra": [{"hypothesis", "stance": +1/-1, "strength", "text"}]}      (extra = hypothetical evidence)
    await ask(belief, question, claims) -> fork(...) + {"question", "mapping_reason", "unmapped"}

For a free-text question the LLM only MAPS the question onto this run's own assumptions, hypothesis priors and evidence
(or adds a clearly-labelled hypothetical piece of evidence); the numbers always come from the belief engine.
"""
from .. import belief as B
from ..ai_runtime import chat_json
from ..ledger import cite_id

ASK_SCHEMA = {"type": "object", "required": ["assumptions", "priors", "drop_claims", "extra", "reason"], "properties": {
    "assumptions": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["id", "p"], "properties": {
        "id": {"type": "string"}, "p": {"type": "number"}}}},
    "priors": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["id", "prior"], "properties": {
        "id": {"type": "string"}, "prior": {"type": "number"}}}},
    "drop_claims": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
    "extra": {"type": "array", "maxItems": 3, "items": {"type": "object", "required": ["hypothesis", "stance", "strength", "text"], "properties": {
        "hypothesis": {"type": "string"}, "stance": {"enum": [1, -1]}, "strength": {"type": "number"}, "text": {"type": "string", "maxLength": 200}}}},
    "reason": {"type": "string", "maxLength": 400}}}
ASK_SYSTEM = ("You translate a decision-maker's what-if question into changes to an existing research model. You may: set an "
              "assumption's likelihood (0.01-0.99); set a hypothesis prior (0.01-0.99) when the scenario changes the starting belief; "
              "drop evidence claims the scenario would invalidate; or add at most 3 hypothetical evidence items (stance +1 supports "
              "the hypothesis, -1 opposes, strength 0.1-1) when nothing existing covers the scenario. Use only ids listed. Change as "
              "little as needed. reason = one or two sentences on how the question maps to these changes.")


def _clip(p):
    return min(max(float(p), 0.01), 0.99)


def fork(bel: dict, changes: dict) -> dict:
    H0, A0, E0 = bel["hypotheses"], bel["assumptions"], bel["evidence"]
    base = B.compute(H0, A0, E0)
    av, pv = changes.get("assumptions") or {}, changes.get("priors") or {}
    drop = set(changes.get("drop_claims") or [])
    A = [dict(a, p=_clip(av[a["id"]])) if a["id"] in av else a for a in A0]
    H = [dict(h, prior=_clip(pv[h["id"]])) if h["id"] in pv else h for h in H0]
    E = [e for e in E0 if e["claim"] not in drop]
    hids = {h["id"] for h in H0}
    extra = [x for x in changes.get("extra") or [] if x.get("hypothesis") in hids]
    for i, x in enumerate(extra):
        E.append({"claim": f"hyp{i + 1}", "cluster": f"hyp{i + 1}", "hypothesis": x["hypothesis"], "stance": 1 if x["stance"] > 0 else -1,
                  "strength": min(max(float(x.get("strength", 0.5)), 0.1), 1.0), "reliability": 0.6, "freshness": 1.0, "domains": 1})
    res = B.compute(H, A, E)
    bh = {h["id"]: h for h in base["hypotheses"]}
    diff = [{"id": h["id"], "before": bh[h["id"]]["p"], "after": h["p"], "delta": round(h["p"] - bh[h["id"]]["p"], 4)} for h in res["hypotheses"]]
    return {"baseline": base, "result": res, "diff": diff, "verdict_delta": round(res["verdict"] - base["verdict"], 4),
            "flips": (base["verdict"] >= 0.5) != (res["verdict"] >= 0.5), "cruxes": B.cruxes(H, A, E),
            "applied": {"assumptions": {k: _clip(v) for k, v in av.items() if any(a["id"] == k for a in A0)},
                        "priors": {k: _clip(v) for k, v in pv.items() if k in hids},
                        "drop_claims": sorted(drop & {e["claim"] for e in E0}), "extra": extra}}


async def ask(bel: dict, question: str, claims: dict, llm=chat_json) -> dict:
    ev = sorted(bel["evidence"], key=lambda e: -e["strength"] * e["reliability"])
    seen, shown = set(), []
    for e in ev:
        if e["claim"] not in seen and e["claim"] in claims:
            seen.add(e["claim"]); shown.append(e)
        if len(shown) >= 40:
            break
    ctx = ("HYPOTHESES:\n" + "\n".join(f"[{h['id']}] prior {h['prior']:.2f}: {h['text']}" for h in bel["hypotheses"])
           + "\nASSUMPTIONS:\n" + "\n".join(f"[{a['id']}] (for {a['hypothesis']}, now {a['p']:.2f}): {a['text']}" for a in bel["assumptions"])
           + "\nEVIDENCE:\n" + "\n".join(f"[{e['claim']}] ({'supports' if e['stance'] > 0 else 'opposes'} {e['hypothesis']}) {claims[e['claim']]['text']}" for e in shown)
           + f"\n\nWHAT-IF QUESTION: {question}")
    j = await llm("whatif.ask", ASK_SYSTEM, ctx, ASK_SCHEMA, 900) or {}
    ch = {"assumptions": {x["id"]: x["p"] for x in j.get("assumptions", []) if "id" in x},
          "priors": {x["id"]: x["prior"] for x in j.get("priors", []) if "id" in x},
          "drop_claims": [cite_id(c) for c in j.get("drop_claims", [])], "extra": j.get("extra", [])}
    out = fork(bel, ch)
    known = {a["id"] for a in bel["assumptions"]} | {h["id"] for h in bel["hypotheses"]} | set(claims)
    unmapped = [k for k in [*ch["assumptions"], *ch["priors"], *ch["drop_claims"]] if k not in known]
    return {**out, "question": question, "mapping_reason": j.get("reason", ""), "unmapped": unmapped,
            "note": "The model only mapped the question onto this run's model; every number comes from the belief engine."}
