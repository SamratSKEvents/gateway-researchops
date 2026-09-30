"""Claim lifecycle: the Challenger attacks the claims the verdict leans on most; the Verifier re-researches each one.

    await run(targets, search, fetch, judge=nli.judge, llm=chat_json) -> [challenge record]

target  = {"id", "text", "domain", "year", "freshness"}
record  = {"claim", "claim_type", "argument", "severity", "requested_action", "query",
           "status", "confidence", "evidence": [{"url", "domain", "title", "quote", "entail", "contradict"}], "notes"}

Claim type comes from the zero-shot classifier. The challenge (argument / severity / follow-up query) comes from the LLM.
The ruling is computed, not generated: the entailment model scores the claim against every sentence of the follow-up pages
from OTHER domains; thresholds below turn the best support / contradiction into a status.
"""
import asyncio
from .. import nli, classify
from ..ai_runtime import chat_json
import re

STATUS_WEIGHT = {   # multiplies the claim's reliability in the belief engine
    "SUPPORTED": 1.15, "PARTIALLY_SUPPORTED": 0.9, "INSUFFICIENT_EVIDENCE": 1.0, "OUTDATED": 0.45, "CONTRADICTED": 0.3,
}
SUPPORT, CONTRA, PARTIAL = 0.7, 0.7, 0.4       # calibration knobs for the ruling
PAGES, SENTS_PER_PAGE = 3, 80

SCHEMA = {"type": "object", "required": ["challenges"], "properties": {"challenges": {"type": "array", "items": {"type": "object",
    "required": ["id", "argument", "severity", "requested_action", "query"], "properties": {
        "id": {"type": "string"}, "argument": {"type": "string", "maxLength": 260},
        "severity": {"enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
        "requested_action": {"type": "string", "maxLength": 160}, "query": {"type": "string", "maxLength": 90}}}}}}
SYSTEM = ("You are the adversarial challenger of a research team. For each claim, find its weakest point: overstatement, a "
          "number without context, a stale figure, a vendor or interested source, correlation taken as causation, or a missing "
          "counter-case. argument = the sharp challenge in one or two sentences. severity = how much the conclusion depends on it "
          "being wrong. requested_action = what the verifier must check. query = a web search query (keywords, no quotes) that "
          "would find independent evidence for OR against the claim. Return every id.")


async def _challenge(targets, llm):
    listing = "\n".join(f"[{t['id']}] ({t.get('domain')}, {t.get('year') or 'undated'}) {t['text']}" for t in targets)
    try:
        j = await llm("challenge.attack", SYSTEM, listing, SCHEMA, 200 + 120 * len(targets))
        got = {str(x.get("id")).strip("[] "): x for x in (j or {}).get("challenges", [])}
    except Exception:
        got = {}
    out = {}
    for t in targets:
        x = got.get(t["id"])
        out[t["id"]] = x or {"argument": "Single-source claim; not yet checked against independent evidence.", "severity": "MEDIUM",
                             "requested_action": "Find an independent source that confirms or refutes it.", "query": t["text"][:90]}
    return out


CONFIRM_SCHEMA = {"type": "object", "required": ["contradicts", "reason"], "properties": {
    "contradicts": {"type": "boolean"}, "reason": {"type": "string", "maxLength": 160}}}
CONFIRM_SYSTEM = ("Does the EVIDENCE sentence directly contradict the CLAIM, i.e. both cannot be true about the same thing? "
                  "Different topics, different companies, or merely different emphasis are NOT contradictions.")


async def _confirm_contradiction(claim, sentence, llm):
    """The entailment model over-calls contradiction between related sentences; the LLM must agree before it counts."""
    try:
        j = await llm("challenge.confirm", CONFIRM_SYSTEM, f"CLAIM: {claim}\nEVIDENCE: {sentence}", CONFIRM_SCHEMA, 150)
        return bool((j or {}).get("contradicts")), (j or {}).get("reason", "")
    except Exception:
        return False, "confirmation unavailable"


def sentences(text: str) -> list[str]:
    """Plain sentence split (text parsing only; no judgement about content)."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if 20 <= len(p.strip()) <= 500]


def rule(best_ent: float, best_con: float, freshness: float) -> str:
    if best_con >= CONTRA and best_con > best_ent:          # support wins ties: one confirming source beats noise
        return "OUTDATED" if freshness < 0.5 else "CONTRADICTED"
    if best_ent >= SUPPORT:
        return "SUPPORTED"
    if max(best_ent, best_con) >= PARTIAL:
        return "PARTIALLY_SUPPORTED"
    return "INSUFFICIENT_EVIDENCE"


async def _verify(t, ch, search, fetch, judge, embed=None, llm=chat_json):
    res = await search(ch["query"])
    pages = [r for r in (res or []) if r.get("url") and t.get("domain", "") not in r["url"]][:PAGES]
    texts = await asyncio.gather(*(fetch(r["url"]) for r in pages))
    cands = []
    for r, txt in zip(pages, texts):
        body = txt or r.get("snippet") or ""
        for s in sentences(body)[:SENTS_PER_PAGE]:
            cands.append((r, s))
    if cands:     # only sentences about the same subject may support or contradict (NLI calls unrelated text a contradiction)
        sims = await classify.relatedness(t["text"], [s for _, s in cands], embed)
        if sims is not None:
            cands = [c for c, sim in sorted(zip(cands, sims), key=lambda x: -x[1]) if sim >= classify.RELATED_MIN][:40]
    if not cands:
        return {"status": "INSUFFICIENT_EVIDENCE", "confidence": 0.5, "evidence": [], "notes": "no follow-up sentence was about the same subject"}
    if judge is nli.judge and not nli.available():
        return {"status": "INSUFFICIENT_EVIDENCE", "confidence": 0.5, "evidence": [], "notes": "verifier model unavailable (GPU entailment model not loaded)"}
    scores = await judge([(s, t["text"]) for _, s in cands])
    scored = sorted(zip(cands, scores), key=lambda x: -max(x[1]["entail"], x[1]["contradict"]))
    for i, ((r, sent), sc) in enumerate(scored[:6]):     # proposed contradictions need a second opinion
        if sc["contradict"] >= CONTRA and sc["contradict"] > sc["entail"]:
            ok, why = await _confirm_contradiction(t["text"], sent, llm)
            if not ok:
                scored[i] = ((r, sent), {**sc, "contradict": 0.0, "rejected_contradiction": why})
    best_ent = max(sc["entail"] for _, sc in scored)
    best_con = max(sc["contradict"] for _, sc in scored)
    status = rule(best_ent, best_con, t.get("freshness", 1.0))
    ev = [{"url": r["url"], "domain": r["url"].split("/")[2] if "//" in r["url"] else r["url"], "title": r.get("title", ""),
           "quote": s, "entail": round(sc["entail"], 3), "contradict": round(sc["contradict"], 3)}
          for (r, s), sc in scored[:3] if max(sc["entail"], sc["contradict"]) >= PARTIAL]
    conf = round(max(best_ent, best_con), 3)
    notes = {"SUPPORTED": f"independent source entails the claim ({best_ent:.0%})",
             "CONTRADICTED": f"independent source contradicts the claim ({best_con:.0%})",
             "OUTDATED": f"newer independent evidence contradicts this dated claim ({best_con:.0%})",
             "PARTIALLY_SUPPORTED": f"related evidence found but not decisive (support {best_ent:.0%}, contradiction {best_con:.0%})",
             "INSUFFICIENT_EVIDENCE": f"nothing in {len(pages)} follow-up page(s) bears on the claim"}[status]
    return {"status": status, "confidence": conf, "evidence": ev, "notes": notes}


async def run(targets: list[dict], search, fetch, judge=nli.judge, llm=chat_json, embed=None) -> list[dict]:
    if not targets:
        return []
    types = await classify.best([t["text"] for t in targets], classify.CLAIM_TYPE)
    attacks = await _challenge(targets, llm)
    verdicts = await asyncio.gather(*(_verify(t, attacks[t["id"]], search, fetch, judge, embed, llm) for t in targets), return_exceptions=True)
    out = []
    for t, (ctype, cp), ch, v in zip(targets, types, (attacks[t["id"]] for t in targets), verdicts):
        if isinstance(v, Exception):
            v = {"status": "INSUFFICIENT_EVIDENCE", "confidence": 0.5, "evidence": [], "notes": f"verification failed: {type(v).__name__}"}
        out.append({"claim": t["id"], "claim_text": t["text"], "claim_type": ctype, "type_confidence": round(cp, 3),
                    "argument": ch["argument"], "severity": ch["severity"], "requested_action": ch["requested_action"],
                    "query": ch["query"], **v})
    return out
