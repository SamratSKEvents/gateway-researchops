import asyncio
from backend.modules import whatif

BEL = {"hypotheses": [{"id": "h1", "text": "demand", "prior": 0.5, "weight": 1, "favours": 1}],
       "assumptions": [{"id": "a1", "text": "cheap service", "hypothesis": "h1", "p": 0.7, "p0": 0.7, "strength": 1}],
       "evidence": [{"claim": "c1", "cluster": "c1", "hypothesis": "h1", "stance": 1, "strength": 0.9, "reliability": 0.8, "freshness": 1, "domains": 1}]}


def test_fork_drop_and_assumption_lower_the_verdict():
    r = whatif.fork(BEL, {"assumptions": {"a1": 0.1}, "drop_claims": ["c1", "c404"]})
    assert r["result"]["verdict"] < r["baseline"]["verdict"] and r["applied"]["drop_claims"] == ["c1"]
    assert r["diff"][0]["delta"] < 0


def test_ask_maps_question_and_engine_computes():
    async def llm(task, system, user, schema, mt):
        assert "WHAT-IF QUESTION: what if servicing is expensive?" in user
        return {"assumptions": [{"id": "a1", "p": 0.15}], "priors": [], "drop_claims": [], "extra": [
            {"hypothesis": "h1", "stance": -1, "strength": 0.6, "text": "servicing costs eat margins"}], "reason": "maps to a1"}
    r = asyncio.run(whatif.ask(BEL, "what if servicing is expensive?", {"c1": {"text": "students want scooters"}}, llm=llm))
    assert r["verdict_delta"] < 0 and r["mapping_reason"] == "maps to a1" and r["applied"]["extra"]
