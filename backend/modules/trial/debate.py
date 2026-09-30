import asyncio
from ..ai_runtime import chat_json
from ..ledger import cite_id

ROLES = {  # role: (title, brief)
    "advocate": ("Advocate", "Argue FOR going ahead. Make the strongest honest case."),
    "challenger": ("Challenger", "Argue AGAINST going ahead. Attack the advocate's points and expose weak or missing evidence."),
    "market": ("Market witness", "Testify only about market size, growth and demand."),
    "competition": ("Competition witness", "Testify only about existing competitors, their prices, services and positions."),
    "customers": ("Customer witness", "Testify only about customer segments, needs and complaints."),
    "regulation": ("Regulation witness", "Testify only about laws, policy, incentives and compliance."),
    "premortem": ("Pre-mortem witness", "It is one year later and the venture FAILED. Explain the most likely causes."),
}
SCHEMA = {"type": "object", "required": ["points"], "properties": {"points": {"type": "array", "maxItems": 4, "items": {"type": "object",
    "required": ["point", "cites"], "properties": {"point": {"type": "string", "maxLength": 300},
                                                  "cites": {"type": "array", "maxItems": 4, "items": {"type": "string"}}}}}}}
RULES = ("You are the {title} in a structured business-decision hearing. {brief} Rules: you may ONLY use the evidence exhibits listed; "
         "every point must cite the exhibit ids it rests on; no outside knowledge; if the exhibits do not cover your topic, say so in one "
         "point with no citations. Give at most 4 short points.")


def exhibits(ledger: list[dict]) -> str:
    """ledger: [{id, text, source_type, domain, year, stance_note}]"""
    return "\n".join(f"[{c['id']}] ({c['source_type']}, {c['domain']}, {c.get('year') or 'undated'}{'; ' + c['stance_note'] if c.get('stance_note') else ''}) "
                     f"\"{c['text']}\"" for c in ledger)


async def _speak(role, context, ledger_ids, llm, before=""):
    title, brief = ROLES[role]
    j = await llm(f"trial.{role}", RULES.format(title=title, brief=brief), context + before, SCHEMA, 900)
    pts = []
    for p in j.get("points", []):
        cites = [cite_id(c) for c in p.get("cites", [])]
        pts.append({"point": str(p.get("point", "")).strip(), "cites": [c for c in cites if c in ledger_ids],
                    "invalid_cites": [c for c in cites if c not in ledger_ids]})
    return {"role": role, "title": title, "points": [p for p in pts if p["point"]]}


async def hold(decision: str, verdict_line: str, ledger: list[dict], llm=chat_json) -> list[dict]:
    """-> [{role, title, points:[{point, cites, invalid_cites}]} | {role, title, error}]. Advocate speaks first; the challenger
    hears the advocate; witnesses and the pre-mortem testify in parallel."""
    ids = {c["id"] for c in ledger}
    context = f"DECISION: {decision}\nCURRENT EVIDENCE-BASED ESTIMATE: {verdict_line}\n\nEVIDENCE EXHIBITS:\n{exhibits(ledger)}"

    async def safe(role, before=""):
        try:
            return await _speak(role, context, ids, llm, before)
        except Exception as e:
            return {"role": role, "title": ROLES[role][0], "points": [], "error": f"{type(e).__name__}: {e}"}

    adv = await safe("advocate")
    heard = "\n\nTHE ADVOCATE ARGUED:\n" + "\n".join(f"- {p['point']} {p['cites']}" for p in adv["points"])
    rest = await asyncio.gather(safe("challenger", heard), *(safe(r) for r in ("market", "competition", "customers", "regulation", "premortem")))
    return [adv, *rest]
