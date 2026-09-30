"""Asks open questions until the decision, scope and success criteria are clear. The run does not start before this."""
import re
from ..ai_runtime import chat_json
from .. import nli

MAX_QUESTIONS = 3
SKIP = {"skip", "no", "n/a", "na", "-", "none", "proceed", "go", "go ahead", "start"}
SCHEMA = {"type": "object", "required": ["ready", "question", "missing"], "properties": {
    "ready": {"type": "boolean"},
    "question": {"type": "string", "maxLength": 240},
    "missing": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 60}}}}
SYSTEM = ("You are a senior strategy consultant scoping a research engagement, not a survey. You get at most 3 questions, so each must "
          "change what gets researched. Think first: what are the 2-3 things about THIS user's situation that would most change the "
          "answer? Typical ones: what decision they actually face and what counts as success; their angle or edge (why them, what they "
          "already have); a hard constraint or deal-breaker. Ask ONE question about the most decision-relevant unknown, and ALWAYS "
          "offer your best guess so the user can just confirm or correct it, e.g. 'I'll assume you want a pilot near 2-3 campuses "
          "within 6 months, judged by paying riders rather than profit - right, or is the goal different?'. "
          "Rules: never drill into the detail of the previous answer (no follow-up on the same topic); each question covers a "
          "DIFFERENT dimension. Never ask for facts, prices, costs or numbers the research can find (e.g. current transport costs, "
          "market size, competitor prices). Never ask something already answered or obvious from the question. No forms, no multiple "
          "choice, no budget or risk-appetite questions unless the user raised them. Keep it under 45 words, plain language. "
          "Set ready=true as soon as the decision, the customer and success are clear enough to research. "
          "missing = points still unclear (they will be treated as stated assumptions).")


def _same(a, b):
    wa, wb = set(re.findall(r"[a-z]{4,}", a.lower())), set(re.findall(r"[a-z]{4,}", b.lower()))
    return len(wa & wb) / (len(wa | wb) or 1) > 0.45


def _transcript(query, qa, known=""):
    return (f"Research question: {query}\n" + (f"Already specified by the user (do not ask about these): {known}\n" if known else "")
            + "".join(f"\nQ: {x['q']}\nA: {x['a']}" for x in qa))


async def _repeats(q, asked) -> bool:
    """Same question asked again? The entailment model checks both directions; lexical overlap only if the GPU model is absent."""
    if not asked:
        return False
    if nli.available():
        sc = await nli.judge([(a, q) for a in asked] + [(q, a) for a in asked])
        n = len(asked)
        return any(sc[i]["entail"] >= 0.8 and sc[n + i]["entail"] >= 0.8 for i in range(n))
    return any(_same(q, a) for a in asked)


async def next_step(query: str, qa: list[dict], llm=chat_json, known: str = "") -> dict:
    """qa: [{q, a}] so far -> {ready, question, goal, missing, how}. Ready after MAX_QUESTIONS or if the user skips."""
    forced = len(qa) >= MAX_QUESTIONS or (qa and qa[-1]["a"].strip().lower() in SKIP)
    goal = _transcript(query, [x for x in qa if x["a"].strip().lower() not in SKIP], known)   # the goal is the user's own words, not a paraphrase
    try:
        j = await llm("goals.interview", SYSTEM, _transcript(query, qa, known) + ("\n\nThe interview is over: set ready=true." if forced else ""),
                      SCHEMA, 600)
        q = str(j["question"]).strip()
        repeat = await _repeats(q, [x["q"] for x in qa])
        out = {"ready": bool(j["ready"]) or forced or repeat, "question": q, "goal": goal,
               "missing": [str(m) for m in j.get("missing", [])], "how": "model"}
    except Exception as e:   # model down: one generic open question, then proceed on the question as stated
        out = {"ready": bool(qa) or forced, "question": "What decision will this research support, and what would a good outcome look like for you?",
               "goal": goal, "missing": [], "how": f"fallback ({type(e).__name__})"}
    if not out["question"]:
        out["ready"] = True
    return out
