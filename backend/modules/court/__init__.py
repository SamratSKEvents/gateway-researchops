"""Evidence Court: a per-claim hearing. Exhibits are chosen by the entailment model (ledger claims that support or contradict
the claim under trial) plus the verifier's follow-up evidence. The LLM writes the hearing but may only cite exhibits; every
cited turn is then checked by the citation verifier, and the ruling is recorded with that verification.

    await hold(claim_id, snap, judge=nli.judge, llm=chat_json) -> hearing record
"""
from .. import nli, trial, classify
from ..ai_runtime import chat_json
from ..ledger import cite_id

MAX_CANDIDATES, SIDE = 160, 4
SCHEMA = {"type": "object", "required": ["turns", "ruling", "rationale"], "properties": {
    "turns": {"type": "array", "minItems": 5, "maxItems": 9, "items": {"type": "object", "required": ["role", "thesis", "points"], "properties": {
        "role": {"enum": ["JUDGE", "CLERK", "PROSECUTION", "DEFENSE"]}, "thesis": {"type": "string", "maxLength": 200},
        "points": {"type": "array", "maxItems": 3, "items": {"type": "object", "required": ["label", "text", "cites"], "properties": {
            "label": {"type": "string", "maxLength": 40}, "text": {"type": "string", "maxLength": 220},
            "cites": {"type": "array", "maxItems": 3, "items": {"type": "string"}}}}}}}},
    "ruling": {"enum": ["AFFIRMED", "QUALIFIED", "OVERRULED"]}, "rationale": {"type": "string", "maxLength": 300}}}
SYSTEM = ("You run an evidence court over ONE business claim. Order: JUDGE opens; CLERK reads the claim and lists the exhibits; "
          "PROSECUTION attacks the claim; DEFENSE answers; they exchange 2-3 rounds; JUDGE rules. Rules: only the listed exhibits "
          "count as evidence, cite their ids on every factual point, no outside knowledge, no invented numbers. Ruling: AFFIRMED "
          "if the exhibits establish the claim, QUALIFIED if they support it only in part or with conditions, OVERRULED if they "
          "contradict it or fail to support it. Format every turn for speech: a one-sentence thesis, then 2-3 short points, each "
          "with a 2-4 word bold-style label (e.g. 'Core risk', 'Price evidence') and the exhibit ids it rests on. No long paragraphs.")


async def _exhibits(claim, others, challenge, judge, embed=None):
    """Other ledger claims ON THE SAME SUBJECT (embedding gate) that the entailment model says support or contradict the claim."""
    cands = [c for c in others if c["id"] != claim["id"] and c.get("cluster") != claim.get("cluster")]
    sims = await classify.relatedness(claim["text"], [c["text"] for c in cands], embed) if cands else []
    if sims is not None:
        cands = [c for c, s in sorted(zip(cands, sims), key=lambda x: -x[1]) if s >= classify.RELATED_MIN]
    cands = cands[:MAX_CANDIDATES]
    sup, con = [], []
    if cands and (judge is not nli.judge or nli.available()):
        scores = await judge([(c["text"], claim["text"]) for c in cands])
        ranked = sorted(zip(cands, scores), key=lambda x: -max(x[1]["entail"], x[1]["contradict"]))
        sup = [dict(c, relation="supports", score=round(s["entail"], 3)) for c, s in ranked if s["entail"] >= 0.5][:SIDE]
        con = [dict(c, relation="contradicts", score=round(s["contradict"], 3)) for c, s in ranked if s["contradict"] >= 0.5][:SIDE]
    ver = [{"id": e["claim_id"], "text": e["quote"], "domain": e["domain"], "relation": "verification",
            "score": max(e["entail"], e["contradict"])} for e in (challenge or {}).get("evidence", []) if e.get("claim_id")]
    return [dict(claim, relation="claim under trial", score=1.0)] + sup + con + ver


async def hold(claim_id: str, snap: dict, judge=nli.judge, llm=chat_json, embed=None) -> dict:
    claims, sources = snap["claims"], snap["sources"]
    if claim_id not in claims:
        raise KeyError(claim_id)
    claim = claims[claim_id]
    ch = next((r for r in snap.get("result", {}).get("challenges", []) if r["claim"] == claim_id), None)
    pool = [c for c in claims.values() if set(c.get("tasks", [])) & set(claim.get("tasks", []))] or list(claims.values())
    ex = await _exhibits(claim, pool, ch, judge, embed)
    ids = {e["id"] for e in ex}
    listing = "\n".join(f"[{e['id']}] ({e['relation']}; {sources.get(claims.get(e['id'], {}).get('source'), {}).get('domain', e.get('domain', ''))}) "
                        f"\"{e['text']}\"" for e in ex)
    ctx = (f"CLAIM UNDER TRIAL [{claim_id}]: \"{claim['text']}\"\n"
           + (f"CHALLENGE ON RECORD: {ch['argument']} (verifier: {ch['status']} — {ch['notes']})\n" if ch else "")
           + f"\nEXHIBITS:\n{listing}")
    j = await llm("court.hearing", SYSTEM, ctx, SCHEMA, 1800)
    turns = []
    for i, t in enumerate((j or {}).get("turns", [])):
        pts, all_cites, bad = [], [], []
        for p in t.get("points", []):
            cs = [cite_id(c) for c in p.get("cites", [])]
            pts.append({"label": str(p.get("label", "")).strip(), "text": str(p.get("text", "")).strip(), "cites": [c for c in cs if c in ids]})
            all_cites += [c for c in cs if c in ids and c not in all_cites]; bad += [c for c in cs if c not in ids]
        thesis = str(t.get("thesis", t.get("statement", ""))).strip()
        statement = thesis + "".join(f"\n• {p['label']}: {p['text']}" for p in pts)      # narration-ready text
        turns.append({"step": i + 1, "role": t.get("role", "JUDGE"), "thesis": thesis, "points": pts, "statement": statement,
                      "cites": all_cites, "invalid_cites": bad})
    stmts = [{"id": f"turn{t['step']}", "text": t["statement"], "cites": t["cites"]} for t in turns if t["cites"]]
    rulings = await trial.verify(stmts, {e["id"]: e["text"] for e in ex}) if stmts else {}
    for t in turns:
        t["verification"] = rulings.get(f"turn{t['step']}", {"ruling": "no citation", "reason": ""})
    return {"claim": claim_id, "claim_text": claim["text"], "exhibits": ex, "turns": turns,
            "ruling": (j or {}).get("ruling", "QUALIFIED"), "rationale": (j or {}).get("rationale", ""),
            "challenge": {k: ch[k] for k in ("argument", "severity", "status", "notes")} if ch else None,
            "struck_turns": sum(t["verification"].get("ruling") == "unsupported" for t in turns)}
