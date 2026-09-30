"""Citation Verifier (the clerk). Independent of the writers: sees only a statement and the verbatim quotes it cites.
Cheap lexical pre-check first (no shared content words -> struck without an LLM call), then an LLM ruling in batches."""
import asyncio, re
from ..ai_runtime import chat_json
from .. import nli

BATCH = 4
SCHEMA = {"type": "object", "required": ["rulings"], "properties": {"rulings": {"type": "array", "items": {"type": "object",
    "required": ["id", "ruling", "reason"], "properties": {"id": {"type": "string"}, "ruling": {"enum": ["supported", "partial", "unsupported"]},
                                                           "reason": {"type": "string", "maxLength": 160}}}}}}
SYSTEM = ("You are a strict citation checker. For each statement, read ONLY its cited quotes. Rule 'supported' if the quotes state what the "
          "statement claims, 'partial' if they support part of it or it overstates them, 'unsupported' if they do not say it. "
          "Judging, not general knowledge. Reason in under 20 words. Return every id.")
STOP = set("that this with from have will their there about which would could should into than then them they been were what when "
           "where more most other some such only also over under very going ahead".split())


def _words(t):
    return {w for w in re.sub(r"[^a-z0-9 ]+", " ", t.lower()).split() if len(w) > 3 and w not in STOP}


def lexical_support(statement: str, quotes: list[str]) -> float:
    s = _words(statement)
    return len(s & _words(" ".join(quotes))) / (len(s) or 1)


def nli_ruling(sc: dict) -> str:
    """Quotes (premise) vs statement (hypothesis). Thresholds are the calibration knob."""
    if sc["entail"] >= 0.7:
        return "supported"
    if sc["contradict"] >= 0.5 or sc["entail"] < 0.3:
        return "unsupported"
    return "partial"


async def _batch(items, claims, llm):
    body = "\n\n".join(f"STATEMENT {it['id']}: {it['text']}\n" + "\n".join(f"  QUOTE [{c}]: \"{claims[c]}\"" for c in it["cites"]) for it in items)
    j = await llm("trial.verify", SYSTEM, body, SCHEMA, 1200)
    return {str(r.get("id")).strip(): (r.get("ruling"), str(r.get("reason", ""))) for r in j.get("rulings", [])}


async def verify(statements: list[dict], claims: dict[str, str], llm=chat_json) -> dict[str, dict]:
    """statements: [{id, text, cites}] ; claims: {claim_id: quote} -> {statement_id: {ruling, reason, by}}.
    ruling: supported | partial | unsupported | unchecked (model unavailable; shown, flagged, never silently trusted)."""
    out, todo = {}, []
    for s in statements:
        cites = [c for c in s["cites"] if c in claims]
        if not cites:
            out[s["id"]] = {"ruling": "unsupported", "reason": "cites no ledger evidence", "by": "rule"}
        elif lexical_support(s["text"], [claims[c] for c in cites]) == 0:
            out[s["id"]] = {"ruling": "unsupported", "reason": "shares no content words with its quotes", "by": "rule"}
        else:
            todo.append({**s, "cites": cites})
    got, by, nli_ids = {}, "model", set()
    if todo and llm is chat_json and nli.available():   # independent entailment model on GPU; the LLM loop below is the fallback
        scores = await nli.judge([(" ".join(claims[c] for c in it["cites"]), it["text"]) for it in todo])
        undecided = []
        for it, sc in zip(todo, scores):
            if sc["entail"] >= 0.7 or sc["contradict"] >= 0.5:      # clear cases: the entailment model rules
                got[it["id"]] = (nli_ruling(sc), f"entailment {sc['entail']:.0%}, contradiction {sc['contradict']:.0%}")
                nli_ids.add(it["id"])
            else:                                                     # paraphrase / synthesis: neutral for NLI -> LLM rules
                undecided.append(it)
        todo = undecided
    for size in (BATCH, 1):          # small models skip ids in a batch: re-ask whatever came back without a ruling, one at a time
        batches = [todo[i:i + size] for i in range(0, len(todo), size)]
        for r in await asyncio.gather(*(_batch(b, claims, llm) for b in batches), return_exceptions=True):
            if isinstance(r, dict):
                got.update({k: v for k, v in r.items() if v[0] in ("supported", "partial", "unsupported")})
        todo = [it for it in todo if it["id"] not in got]
    for s in statements:
        if s["id"] not in out:
            ruling, reason = got.get(s["id"], (None, ""))
            out[s["id"]] = ({"ruling": ruling, "reason": reason, "by": "nli" if s["id"] in nli_ids else by} if ruling else
                            {"ruling": "unchecked", "reason": "verifier unavailable", "by": "none"})
    return out
