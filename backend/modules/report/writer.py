import asyncio, re
from ..ai_runtime import chat_json
from ..ledger import cite_id

ITEM = {"type": "object", "required": ["text", "cites"], "properties": {"text": {"type": "string", "maxLength": 320},
                                                                     "cites": {"type": "array", "maxItems": 5, "items": {"type": "string"}}}}
SUMMARY_SCHEMA = {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "array", "maxItems": 9, "items": ITEM}}}
ACTIONS_SCHEMA = {"type": "object", "required": ["must_do", "must_not"], "properties": {
    "must_do": {"type": "array", "maxItems": 5, "items": ITEM}, "must_not": {"type": "array", "maxItems": 5, "items": ITEM}}}
COMMON = ("Use ONLY the evidence and hearing record given, no outside knowledge. Every item cites the evidence ids (like c12) it rests "
          "on in `cites`; an item you cannot cite must not be written. Do not put ids or hypothesis numbers in the text. Say 'reportedly' "
          "for single-source facts and 'users say' for opinions.")
SUMMARY_SYSTEM = ("You write the summary of a decision report for a business decision-maker. 5-8 sentences that answer the decision "
                  "directly, state the estimate, say where sources disagree and what is still unknown. Write about the market and the "
                  "business, never about 'the hearing', 'exhibits' or 'the advocate'. " + COMMON)
ACTIONS_SYSTEM = ("You recommend actions for a company based on research evidence. must_do: 2-5 things the company should do; must_not: "
                  "2-5 things it should avoid. Each is ONE imperative sentence starting with a verb, about the business (who to target "
                  "first, what price to stay under, which risk to mitigate, which partner or area to start with), e.g. 'Start with "
                  "delivery riders, who reportedly ride 100+ km a day' or 'Avoid pricing above what riders say they pay for petrol'. "
                  "Never research steps like 'analyse the evidence' or comments about hypotheses. " + COMMON)
RESEARCH_STEP = re.compile(r"(?:identify|analy[sz]e|evaluate|determine|assess|review|consider|investigate|research|study|examine|"
                           r"understand|explore|look into)\b", re.I)
REF = re.compile(r"\s*[\(\[]\s*(?:[ch]?\d+\s*[,;]?\s*)+[\)\]]|\b[ch]\d+\b")


async def draft(context: str, valid_ids: set, llm=chat_json) -> dict:
    """-> {summary|must_do|must_not: [{id, text, cites, invalid_cites}]} ; items with no valid citation are kept but flagged
    (the verifier strikes them)."""
    s, a = await asyncio.gather(llm("report.summary", SUMMARY_SYSTEM, context, SUMMARY_SCHEMA, 1600),
                                llm("report.actions", ACTIONS_SYSTEM, context, ACTIONS_SCHEMA, 1200), return_exceptions=True)
    if isinstance(s, Exception) and isinstance(a, Exception):
        raise s
    j = {**(s if isinstance(s, dict) else {}), **(a if isinstance(a, dict) else {})}
    out, seen = {}, set()
    for sec, prefix in (("summary", "r"), ("must_do", "d"), ("must_not", "n")):
        items = []
        for i, it in enumerate(j.get(sec, [])):
            cites = [cite_id(c) for c in it.get("cites", [])]
            text = re.sub(r"\s+([,.;])", r"\1", REF.sub("", str(it.get("text", "")))).strip()
            key = text.lower()[:80]
            if not text or key in seen or (sec != "summary" and RESEARCH_STEP.match(text)):
                # small models copy summary sentences into the action lists, or "recommend" more research instead of an action
                continue
            seen.add(key)
            items.append({"id": f"{prefix}{i + 1}", "text": text, "cites": [c for c in cites if c in valid_ids],
                          "invalid_cites": [c for c in cites if c not in valid_ids]})
        out[sec] = items
    return out
