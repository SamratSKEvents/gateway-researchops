"""Follow-up questions on a run, answered by retrieval-augmented generation (RAG).

    await answer(snap, question) -> {"question", "answer": [{text, cites}], "evidence", "verification", "needs_more_research"}

Retrieval: the run's own claims ranked by embedding similarity to the question, plus the closest passages from the global
document store (every page any run has read). The LLM may only cite retrieved items; every cited sentence is then checked by
the citation verifier. If the retrieved evidence does not cover the question, it says so and flags needs_more_research.
"""
from .. import classify, trial
from ..ai_runtime import chat_json, embed
from ..ledger import cite_id

TOP_CLAIMS, TOP_PASSAGES = 14, 5
SCHEMA = {"type": "object", "required": ["answer", "covered"], "properties": {
    "answer": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["text", "cites"], "properties": {
        "text": {"type": "string", "maxLength": 400}, "cites": {"type": "array", "maxItems": 3, "items": {"type": "string"}}}}},
    "covered": {"type": "boolean"}}}
SYSTEM = ("Answer the decision-maker's follow-up question using ONLY the evidence listed. Write 2-6 short sentences; every "
          "factual sentence cites the evidence ids it rests on. If the evidence does not answer the question, say what is "
          "missing and set covered=false. No outside knowledge.")


async def retrieve(snap: dict, question: str) -> list[dict]:
    claims = list(snap["claims"].values())
    ev_ids = {e["claim"] for e in ((snap.get("result") or {}).get("belief") or {}).get("evidence", [])}
    pool = sorted(claims, key=lambda c: (c["id"] not in ev_ids, c.get("freshness", 1) < 0.5))[:400]   # weighed evidence first
    sims = await classify.relatedness(question, [c["text"] for c in pool])
    if sims is None:
        sims = [0.0] * len(pool)
    ranked = sorted(zip(pool, sims), key=lambda x: -x[1])[:TOP_CLAIMS]
    out = [{"id": c["id"], "text": c["text"], "kind": "claim", "score": s,
            "domain": snap["sources"].get(c["source"], {}).get("domain", ""), "url": snap["sources"].get(c["source"], {}).get("url")}
           for c, s in ranked]
    try:
        from ..store import db
        qv = await embed([f"search_query: {question}"])
        for i, p in enumerate(db.search(question, TOP_PASSAGES, qvec=qv[0] if qv else None)):
            out.append({"id": f"d{i + 1}", "text": p["text"][:700], "kind": "passage", "score": p["score"], "domain": p["domain"], "url": p["url"]})
    except Exception:
        pass
    return out


async def answer(snap: dict, question: str, llm=chat_json) -> dict:
    ev = await retrieve(snap, question)
    ids = {e["id"] for e in ev}
    ctx = f"DECISION: {snap['query']}\nQUESTION: {question}\n\nEVIDENCE:\n" + "\n".join(f"[{e['id']}] ({e['domain']}) {e['text']}" for e in ev)
    j = await llm("ask.answer", SYSTEM, ctx, SCHEMA, 900) or {}
    items = []
    for i, a in enumerate(j.get("answer", [])):
        cites = [c for c in (cite_id(x) for x in a.get("cites", [])) if c in ids]
        items.append({"id": f"a{i + 1}", "text": str(a.get("text", "")).strip(), "cites": cites})
    rulings = await trial.verify([it for it in items if it["cites"]], {e["id"]: e["text"] for e in ev}) if items else {}
    for it in items:
        it["ruling"] = rulings.get(it["id"], {}).get("ruling", "no citation")
    return {"question": question, "answer": items, "evidence": ev, "needs_more_research": not j.get("covered", True),
            "verification": {k: sum(it["ruling"] == k for it in items) for k in ("supported", "partial", "unsupported", "no citation")}}
