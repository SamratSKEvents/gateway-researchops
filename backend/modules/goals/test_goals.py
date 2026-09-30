import asyncio
from backend.modules.goals import next_step, build, MAX_QUESTIONS


def fake(reply):
    async def llm(task, system, user, schema, max_tokens):
        if isinstance(reply, Exception):
            raise reply
        return reply(user) if callable(reply) else reply
    return llm


def run(c):
    return asyncio.run(c)


def test_interview_asks_until_ready():
    r = run(next_step("EV scooters Bengaluru?", [], fake({"ready": False, "question": "Who are the customers?", "goal": "g", "missing": ["customers"]})))
    assert not r["ready"] and r["question"] == "Who are the customers?"


def test_interview_is_forced_ready_after_max_questions_or_skip():
    never = fake({"ready": False, "question": "more?", "goal": "g", "missing": []})
    qa = [{"q": "q", "a": "a"}] * MAX_QUESTIONS
    assert run(next_step("x", qa, never))["ready"]
    assert run(next_step("x", [{"q": "q", "a": "skip"}], never))["ready"]


def test_interview_fallback_when_model_down_asks_then_proceeds():
    down = fake(RuntimeError("down"))
    assert not run(next_step("x", [], down))["ready"]
    assert run(next_step("x", [{"q": "q", "a": "for commuters"}], down))["ready"]


def test_hypotheses_are_clamped_and_assumptions_linked():
    j = {"decision": "Launch?", "hypotheses": [
        {"text": "Demand exists", "prior": 1.7, "importance": 0.9, "good_if_true": True, "search_terms": ["demand"]},
        {"text": "Regulation blocks", "prior": 0.2, "importance": 0.5, "good_if_true": False, "search_terms": []},
        {"text": "Price room", "prior": "x", "importance": 0.5, "good_if_true": True, "search_terms": ["price"]}],
        "assumptions": [{"text": "commuters pay monthly", "hypothesis": 9, "belief": 0.7, "strength": 5}]}
    r = run(build("q", "g", fake(j)))
    h1, h2, h3 = r["hypotheses"]
    assert (h1["prior"], h2["favours"], h3["prior"]) == (0.95, -1, 0.5)
    assert h2["search_terms"]                                                       # filled from the question
    a = r["assumptions"][0]
    assert (a["hypothesis"], a["p"], a["p0"], a["strength"]) == ("h3", 0.7, 0.7, 1)


def test_hypotheses_fallback_template():
    r = run(build("scooters", "g", fake(RuntimeError("down"))))
    assert len(r["hypotheses"]) == 4 and r["how"].startswith("fallback")


def test_interview_stops_when_model_repeats_itself_and_goal_is_users_words():
    same = fake({"ready": False, "question": "What metrics indicate success for this launch?", "missing": []})
    r = run(next_step("Scooters?", [{"q": "What metrics would indicate success for this launch?", "a": "2,000 subscribers"}], same))
    assert r["ready"] and "2,000 subscribers" in r["goal"]
