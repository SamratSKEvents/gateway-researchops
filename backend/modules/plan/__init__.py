"""Plan generator: turns a finished decision into a phased action roadmap. Each phase has a measurable go/no-go gate tied to
the run's cruxes and audit follow-ups, and cites the evidence it rests on.

    await generate(snap, llm) -> {"phases": [{name, horizon, actions, gate, risks_addressed, cites}], "first_step"}
"""
from ..ai_runtime import chat_json
from ..ledger import cite_id

SCHEMA = {"type": "object", "required": ["phases", "first_step"], "properties": {
    "first_step": {"type": "string", "maxLength": 200},
    "phases": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "object",
        "required": ["name", "horizon", "actions", "gate", "risks_addressed", "cites"], "properties": {
            "name": {"type": "string", "maxLength": 60}, "horizon": {"type": "string", "maxLength": 30},
            "actions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 160}},
            "gate": {"type": "string", "maxLength": 200},
            "risks_addressed": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 120}},
            "cites": {"type": "array", "maxItems": 4, "items": {"type": "string"}}}}}}}
SYSTEM = ("Turn this research decision into a phased action plan (2-4 phases, e.g. validate -> pilot -> scale). Each phase: concrete "
          "actions, a MEASURABLE go/no-go gate (a number or observable outcome) that tests the cruxes, the risks it retires, and the "
          "evidence ids it rests on. If the verdict is uncertain, start with the cheapest experiment that resolves the biggest crux. "
          "Only use the material given.")


async def generate(snap: dict, llm=chat_json) -> dict:
    R, claims = snap["result"], snap["claims"]
    rep = R.get("report") or {}
    v = rep.get("verdict") or {}
    cruxes = "; ".join((c.get("text") or claims.get(c.get("claim"), {}).get("text", "")) for c in rep.get("cruxes", []))
    ctx = (f"DECISION: {snap['query']}\nVERDICT: {v.get('label')} {v.get('p', 0):.0%} (range {v.get('low', 0):.0%}-{v.get('high', 0):.0%})\n"
           f"MUST DO: {'; '.join(x['text'] for x in rep.get('must_do', []))}\nMUST NOT: {'; '.join(x['text'] for x in rep.get('must_not', []))}\n"
           f"CRUXES: {cruxes}\nAUDIT FOLLOW-UPS: {'; '.join(f['question'] for f in (R.get('autopsy') or {}).get('followups', [])[:6])}\n"
           "EVIDENCE:\n" + "\n".join(f"[{e}] {claims[e]['text']}" for e in (R.get("trial") or {}).get("exhibits", [])[:24] if e in claims))
    j = await llm("plan.generate", SYSTEM, ctx, SCHEMA, 1400) or {}
    for p in j.get("phases", []):
        p["cites"] = [c for c in (cite_id(x) for x in p.get("cites", [])) if c in claims]
    return {"phases": j.get("phases", []), "first_step": j.get("first_step", "")}
