"""Turns the confirmed goal into 3-6 testable hypotheses with priors, plus the assumptions behind them (what-if sliders)."""
from ..ai_runtime import chat_json

SCHEMA = {"type": "object", "required": ["decision", "hypotheses", "assumptions"], "properties": {
    "decision": {"type": "string", "maxLength": 160},
    "hypotheses": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "object",
        "required": ["text", "prior", "importance", "good_if_true", "search_terms"], "properties": {
            "text": {"type": "string", "maxLength": 160}, "prior": {"type": "number"}, "importance": {"type": "number"},
            "good_if_true": {"type": "boolean"},
            "search_terms": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 60}}}}},
    "assumptions": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["text", "hypothesis", "belief", "strength"],
        "properties": {"text": {"type": "string", "maxLength": 160}, "hypothesis": {"type": "integer"},
                       "belief": {"type": "number"}, "strength": {"type": "number"}}}}}}
SYSTEM = ("You turn a business decision into testable hypotheses for research. Write 3-6 hypotheses that together decide the question "
          "(e.g. demand, competition, pricing room, unit economics, regulation, execution). Each: a falsifiable statement; prior = your honest "
          "starting probability 0.05-0.95 that it is true (use 0.5 when unsure); importance 0.1-1 for the decision; good_if_true = whether it "
          "being true favours going ahead; search_terms = web search queries that would find evidence for or against it. "
          "assumptions = 2-4 beliefs about customers, the market or the user's own capabilities that the hypotheses rest on and that the user "
          "may know better than public sources (e.g. 'delivery riders prefer a fixed monthly fee to per-trip charges', 'we can service "
          "scooters at under 10% of revenue'); NEVER restate the user's goal, target or question as an assumption and never use generic "
          "fields like budget; "
          "hypothesis = 1-based index of the hypothesis it affects; belief = how likely you assume it holds (0.05-0.95); strength 0.2-1 = how "
          "much it matters to that hypothesis. decision = the go / no-go question in one line.")
FALLBACK = [("There is meaningful unmet customer demand", True, "demand customers"),
            ("Existing competitors leave room on price or service", True, "competitors pricing"),
            ("The unit economics can be profitable at achievable prices", True, "costs margins profitability"),
            ("Regulation or policy creates a significant barrier", False, "regulation policy rules")]


def _clamp(x, lo, hi, default):
    try:
        return min(max(float(x), lo), hi)
    except (TypeError, ValueError):
        return default


def normalise(j, query):
    hyps = [{"id": f"h{i + 1}", "text": str(h["text"]), "prior": round(_clamp(h.get("prior"), 0.05, 0.95, 0.5), 2),
             "weight": round(_clamp(h.get("importance"), 0.1, 1, 0.5), 2), "favours": 1 if h.get("good_if_true", True) else -1,
             "search_terms": [str(t) for t in h.get("search_terms", []) if str(t).strip()][:4] or [f"{query} {h['text']}"[:90]]}
            for i, h in enumerate(j["hypotheses"])]
    assumptions = []
    for a in j.get("assumptions", []):
        idx = int(_clamp(a.get("hypothesis"), 1, len(hyps), 1)) - 1
        p = round(_clamp(a.get("belief"), 0.05, 0.95, 0.5), 2)
        assumptions.append({"id": f"a{len(assumptions) + 1}", "text": str(a["text"]), "hypothesis": hyps[idx]["id"], "p": p, "p0": p,
                            "strength": round(_clamp(a.get("strength"), 0.2, 1, 0.5), 2)})
    return {"decision": str(j.get("decision") or query), "hypotheses": hyps, "assumptions": assumptions}


async def build(query: str, goal: str, llm=chat_json) -> dict:
    try:
        j = await llm("goals.hypotheses", SYSTEM, f"Research question: {query}\nUser's goal: {goal}", SCHEMA, 1400)
        out = normalise(j, query)
        if len(out["hypotheses"]) < 2:
            raise ValueError("too few hypotheses")
        return {**out, "how": "model"}
    except Exception as e:
        j = {"decision": query, "assumptions": [], "hypotheses": [{"text": t, "prior": 0.5, "importance": 1, "good_if_true": g,
                                                                   "search_terms": [f"{query} {s}"[:90]]} for t, g, s in FALLBACK]}
        return {**normalise(j, query), "how": f"fallback template ({type(e).__name__})"}
