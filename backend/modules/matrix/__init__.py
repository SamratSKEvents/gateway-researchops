"""Comparison matrix: the options/competitors in the evidence x the attributes that matter for this decision.
Every filled cell cites the claim(s) it comes from; anything not stated in a cited claim stays empty (never guessed).

    await build(snap, llm) -> {"rows": [names], "columns": [attributes], "cells": {row: {col: {value, cites}}}, "coverage"}
"""
from ..ai_runtime import chat_json
from ..ledger import cite_id

SCHEMA = {"type": "object", "required": ["rows", "columns", "cells"], "properties": {
    "rows": {"type": "array", "minItems": 2, "maxItems": 10, "items": {"type": "string", "maxLength": 40}},
    "columns": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "string", "maxLength": 40}},
    "cells": {"type": "array", "maxItems": 60, "items": {"type": "object", "required": ["row", "column", "value", "cites"], "properties": {
        "row": {"type": "string"}, "column": {"type": "string"}, "value": {"type": "string", "maxLength": 80},
        "cites": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}}}}}}}
SYSTEM = ("Build a comparison matrix for this business decision. rows = the specific companies, products or options the evidence "
          "names (competitors first; include 'Proposed offering' only if the evidence describes it). columns = the 3-6 attributes "
          "that matter most for the decision (e.g. monthly price, coverage, fleet size, business model, funding, customer segment). "
          "Fill a cell ONLY when a listed claim states it, with a short value and the claim id(s); otherwise leave it out.")


def _candidate_claims(snap, n=90):
    """Claims likely to describe named players: those with prices, then weighed evidence, then the rest."""
    cl = snap["claims"]
    ev = {e["claim"] for e in ((snap.get("result") or {}).get("belief") or {}).get("evidence", [])}
    names = [e["name"].lower() for e in (snap.get("result") or {}).get("entities", [])]
    def score(c):
        t = c["text"].lower()
        return (bool(c.get("prices")) * 2 + (c["id"] in ev) + sum(nm in t for nm in names) * 1.5)
    return sorted(cl.values(), key=score, reverse=True)[:n]


async def build(snap: dict, llm=chat_json) -> dict:
    claims = _candidate_claims(snap)
    ctx = f"DECISION: {snap['query']}\n\nCLAIMS:\n" + "\n".join(f"[{c['id']}] {c['text']}" for c in claims)
    j = await llm("matrix.build", SYSTEM, ctx, SCHEMA, 2000) or {}
    rows, cols, valid = list(dict.fromkeys(j.get("rows", []))), list(dict.fromkeys(j.get("columns", []))), set(snap["claims"])
    cells = {r: {} for r in rows}
    for c in j.get("cells", []):
        cs = [x for x in (cite_id(y) for y in c.get("cites", [])) if x in valid]
        if c.get("row") in cells and c.get("column") in cols and cs and str(c.get("value", "")).strip():
            cells[c["row"]][c["column"]] = {"value": str(c["value"]).strip(), "cites": cs}
    rows = [r for r in rows if cells[r]]            # drop rows with no supported cell
    filled = sum(len(cells[r]) for r in rows)
    return {"rows": rows, "columns": cols, "cells": {r: cells[r] for r in rows},
            "coverage": round(filled / (len(rows) * len(cols)), 3) if rows and cols else 0}
