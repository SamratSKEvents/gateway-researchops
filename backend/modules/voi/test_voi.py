import asyncio
from backend.modules.belief import compute
from backend.modules.voi import rank_gaps, question_for_user, followup_queries

H = [{"id": "h1", "text": "demand exists", "prior": 0.5, "weight": 1, "favours": 1, "search_terms": ["demand"]},
     {"id": "h2", "text": "regulation blocks", "prior": 0.5, "weight": 0.2, "favours": -1, "search_terms": []}]
EV = [{"claim": f"c{i}", "cluster": f"c{i}", "hypothesis": "h2", "stance": -1, "strength": 1, "reliability": 1, "freshness": 1, "domains": 1}
      for i in range(4)]


def test_important_undecided_thin_hypothesis_ranks_first():
    gaps = rank_gaps(H, compute(H, [], EV))
    assert gaps[0]["hypothesis"] == "h1"
    assert all(g["hypothesis"] != "h2" for g in gaps)       # h2 is settled and unimportant


def test_user_is_asked_only_about_assumptions_that_matter():
    A = [{"id": "a1", "text": "commuters pay monthly", "hypothesis": "h1", "p": 0.6, "p0": 0.6, "strength": 1},
         {"id": "a2", "text": "minor detail", "hypothesis": "h2", "p": 0.6, "p0": 0.6, "strength": 0.05}]
    q = question_for_user(H, A, EV, asked=set())
    assert q["assumption"] == "a1" and q["swing"] > 0.3
    assert question_for_user(H, A, EV, asked={"a1"}) is None


def test_followups_drop_tried_and_fall_back_to_search_terms():
    async def llm(*a):
        return {"queries": ["yulu price 2025", "demand", " "]}
    assert asyncio.run(followup_queries(H[0], ["demand"], ["Yulu"], llm)) == ["yulu price 2025"]

    async def down(*a):
        raise RuntimeError
    assert asyncio.run(followup_queries(H[0], [], [], down)) == ["demand"]
