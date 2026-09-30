"""The only LLM step of the Belief Engine: label whether a claim supports or opposes a hypothesis, and how directly.
Candidates are chosen by code (word overlap x source authority, one claim per independence cluster)."""
import asyncio, re
from ..ai_runtime import chat_json
from ..ledger import cite_id
from .. import nli

BATCH, PER_HYP = 12, 24
SCHEMA = {"type": "object", "required": ["labels"], "properties": {"labels": {"type": "array", "items": {"type": "object",
    "required": ["id", "stance", "strength"], "properties": {"id": {"type": "string"}, "stance": {"enum": ["supports", "opposes", "irrelevant"]},
                                                             "strength": {"type": "number"}}}}}}
SYSTEM = ("You label evidence for one hypothesis. For each statement decide if it supports the hypothesis, opposes it, or is irrelevant "
          "(off-topic, too vague, or about something else). strength 0.1-1 = how directly it bears on the hypothesis (1 = direct, specific, "
          "quantified; 0.3 = indirect or general). Judge only what the statement says. Return every id.")
STOP = set("that this with from have will their there about which would could should into than then them they been were what when where "
           "your more most other some such only also over under very".split())


def words(t):
    return {w for w in re.sub(r"[^a-z0-9 ]+", " ", t.lower()).split() if len(w) > 3 and w not in STOP}


def candidates(h: dict, claims: list[dict], done: set, n=PER_HYP) -> list[dict]:
    """claims: [{id, text, cluster, authority}] -> best new claims for hypothesis h, one per cluster."""
    hw = words(h["text"] + " " + " ".join(h.get("search_terms", [])))
    scored = []
    for c in claims:
        if (h["id"], c["id"]) in done:
            continue
        overlap = len(hw & words(c["text"]))
        if overlap >= 2:
            scored.append((overlap * (0.5 + c.get("authority", 0.5)), c))
    scored.sort(key=lambda x: -x[0])
    out, clusters = [], set()
    for _, c in scored:
        if c["cluster"] not in clusters:
            clusters.add(c["cluster"]); out.append(c)
        if len(out) >= n:
            break
    return out


async def _label(h, batch, llm):
    listing = "\n".join(f"[{c['id']}] {c['text']}" for c in batch)
    j = await llm("belief.stance", SYSTEM, f"HYPOTHESIS: {h['text']}\n\nSTATEMENTS:\n{listing}", SCHEMA, 900)
    ids = {c["id"] for c in batch}
    out = []
    for lab in j.get("labels", []):
        cid = cite_id(lab.get("id", ""))
        if cid in ids and lab.get("stance") in ("supports", "opposes"):
            out.append({"claim": cid, "hypothesis": h["id"], "stance": 1 if lab["stance"] == "supports" else -1,
                        "strength": round(min(max(float(lab.get("strength") or 0.5), 0.1), 1.0), 2)})
    return out


def nli_stance(h, c, sc, min_p=0.5):
    """Claim (premise) vs hypothesis: entailment supports, contradiction opposes, neutral is irrelevant. strength = that probability."""
    if max(sc["entail"], sc["contradict"]) < min_p:
        return None
    sign = 1 if sc["entail"] >= sc["contradict"] else -1
    return {"claim": c["id"], "hypothesis": h["id"], "stance": sign,
            "strength": round(min(max(max(sc["entail"], sc["contradict"]), 0.1), 1.0), 2)}


async def _label_nli(pairs):
    scores = await nli.judge([(c["text"], h["text"]) for h, c in pairs])
    return [x for (h, c), sc in zip(pairs, scores) if (x := nli_stance(h, c, sc))]


async def label(hypotheses: list[dict], claims: list[dict], done: set, llm=chat_json) -> tuple[list[dict], set, int]:
    """-> (new stance labels, updated done set, failed batches). `done` holds (hypothesis, claim) pairs already judged."""
    jobs = []
    for h in hypotheses:
        cand = candidates(h, claims, done)
        done |= {(h["id"], c["id"]) for c in cand}
        jobs += [(h, cand[i:i + BATCH]) for i in range(0, len(cand), BATCH)]
    if jobs and llm is chat_json and nli.available():   # GPU entailment model: reproducible labels, no LLM call
        try:
            return await _label_nli([(h, c) for h, b in jobs for c in b]), done, 0
        except Exception:   # noqa: BLE001 — fall through to the LLM
            pass
    res = await asyncio.gather(*(_label(h, b, llm) for h, b in jobs), return_exceptions=True)
    return [x for r in res if not isinstance(r, Exception) for x in r], done, sum(isinstance(r, Exception) for r in res)
