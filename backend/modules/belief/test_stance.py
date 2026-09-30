import asyncio
from backend.modules.belief.stance import candidates, label

H = {"id": "h1", "text": "Commuters in Bengaluru want monthly scooter subscriptions", "search_terms": ["scooter subscription demand"]}
CLAIMS = [{"id": "c1", "text": "Demand for scooter subscriptions among Bengaluru commuters doubled.", "cluster": "c1", "authority": 0.75},
          {"id": "c2", "text": "Demand for scooter subscriptions among Bengaluru commuters doubled last year.", "cluster": "c1", "authority": 0.5},
          {"id": "c3", "text": "Monthly scooter subscriptions were cancelled by many commuters.", "cluster": "c3", "authority": 0.45},
          {"id": "c4", "text": "The weather in Mysuru is pleasant.", "cluster": "c4", "authority": 0.9}]


def test_candidates_one_per_cluster_and_skip_irrelevant_and_done():
    ids = [c["id"] for c in candidates(H, CLAIMS, set())]
    assert ids == ["c1", "c3"]
    assert [c["id"] for c in candidates(H, CLAIMS, {("h1", "c1")})] == ["c2", "c3"]


def test_label_keeps_only_valid_ids_and_real_stances():
    async def llm(task, system, user, schema, max_tokens):
        assert "[c1]" in user and "[c4]" not in user
        return {"labels": [{"id": "c1", "stance": "supports", "strength": 0.9}, {"id": "[c3]", "stance": "opposes", "strength": 7},
                           {"id": "c99", "stance": "supports", "strength": 1}]}
    ev, done, failed = asyncio.run(label([H], CLAIMS, set(), llm))
    assert [(e["claim"], e["stance"], e["strength"]) for e in ev] == [("c1", 1, 0.9), ("c3", -1, 1.0)]
    assert ("h1", "c1") in done and failed == 0


def test_label_survives_model_failure():
    async def llm(*a):
        raise RuntimeError("down")
    ev, _, failed = asyncio.run(label([H], CLAIMS, set(), llm))
    assert ev == [] and failed == 1
