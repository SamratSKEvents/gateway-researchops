from ..ai_runtime import chat_json
from ..belief import compute

SCHEMA = {"type": "object", "required": ["queries"], "properties": {"queries": {"type": "array", "maxItems": 3,
                                                                              "items": {"type": "string", "maxLength": 90}}}}
SYSTEM = ("You write follow-up web search queries for a research agent. The hypothesis below is uncertain and matters for the decision. "
          "Write 2-3 specific search queries (keywords, no quotes) that would find decisive evidence FOR or AGAINST it: prefer named "
          "companies, prices, numbers, dates, official sources. Go deeper than the queries already tried.")


def rank_gaps(hypotheses, belief, min_voi=0.05):
    """VOI ~ importance x how undecided it is x how thin its evidence is. -> [{hypothesis, voi, why}] best first."""
    by = {x["id"]: x for x in belief["hypotheses"]}
    tw = sum(h["weight"] for h in hypotheses) or 1
    out = []
    for h in hypotheses:
        b = by[h["id"]]
        undecided = 4 * b["p"] * (1 - b["p"])          # 1 at 50%, 0 when certain
        thin = 1 / (1 + b["n_eff"])                    # 1 with no evidence
        voi = round(h["weight"] / tw * undecided * (0.3 + 0.7 * thin), 4)
        if voi >= min_voi:
            out.append({"hypothesis": h["id"], "voi": voi,
                        "why": f"p={b['p']:.0%}, {b['clusters']} independent evidence cluster(s), importance {h['weight']}"})
    return sorted(out, key=lambda g: -g["voi"])


def question_for_user(hypotheses, assumptions, evidence, asked: set, swing=0.08):
    """The unasked assumption whose reversal moves the verdict most, if that is more than `swing` or flips the verdict."""
    base = compute(hypotheses, assumptions, evidence)["verdict"]
    best = None
    for a in assumptions:
        if a["id"] in asked:
            continue
        lo = compute(hypotheses, [dict(x, p=0.1) if x["id"] == a["id"] else x for x in assumptions], evidence)["verdict"]
        hi = compute(hypotheses, [dict(x, p=0.9) if x["id"] == a["id"] else x for x in assumptions], evidence)["verdict"]
        flips = (lo >= 0.5) != (hi >= 0.5)
        if (hi - lo >= swing or flips) and (best is None or hi - lo > best["swing"]):
            best = {"assumption": a["id"], "text": a["text"], "swing": round(hi - lo, 4), "flips": flips, "verdict": base,
                    "question": (f"Quick check before I conclude. Right now the evidence leans "
                                 f"{'in favour' if base >= 0.5 else 'against'} ({base:.0%} favourable), but part of that rests on "
                                 f"something public sources can't tell me: \"{a['text']}\". I've been treating this as likely "
                                 f"(~{a['p']:.0%}). If it's not true for you, the recommendation "
                                 f"{'could flip' if flips else f'shifts by up to {hi - lo:.0%}'}. Is it true in your case? "
                                 f"Yes / no / not sure, or add a line of context.")}
    return best


async def followup_queries(h, tried: list[str], entities: list[str], llm=chat_json) -> list[str]:
    user = (f"Hypothesis: {h['text']}\nQueries already tried: {'; '.join(tried[-8:]) or 'none'}\n"
            f"Names found so far in the evidence: {', '.join(entities[:12]) or 'none'}")
    try:
        j = await llm("voi.followup", SYSTEM, user, SCHEMA, 300)
        qs = [q.strip() for q in j["queries"] if q.strip() and q.strip() not in tried]
    except Exception:
        qs = []
    return qs[:3] or [t for t in h.get("search_terms", []) if t not in tried][:2]
