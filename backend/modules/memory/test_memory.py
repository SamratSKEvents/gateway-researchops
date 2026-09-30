import asyncio
from backend.modules import memory


def run_(rid, q, texts, ents=()):
    claims = {f"c{i}": {"id": f"c{i}", "text": t, "source": "s1", "freshness": 0.9} for i, t in enumerate(texts, 1)}
    return {"id": rid, "query": q, "status": "done", "created": 1, "claims": claims, "sources": {"s1": {"domain": "news.com", "type": "news"}},
            "result": {"entities": [{"name": e, "category": "company"} for e in ents],
                       "report": {"verdict": {"label": "favourable", "p": 0.7}, "gaps": [{"text": "no churn data"}]}}}


def test_memory_relevance_recurring_entities_contradictions():
    a = run_("r1", "e-scooter subscriptions in Bengaluru", ["Yulu operates 18,000 scooters in Bengaluru today.", "Demand is rising fast."], ["Yulu"])
    b = run_("r2", "bike rentals in Bengaluru", ["Yulu operates 18,000 scooters in Bengaluru today.", "Demand is falling fast."], ["Yulu", "Bounce"])
    c = run_("r3", "dental SaaS in Pune", ["Clinics buy software yearly."])

    async def embed(texts):
        return [[1, 0] if "Bengaluru" in t else [0, 1] for t in texts]

    async def judge(pairs):
        return [{"entail": 0, "neutral": 0, "contradict": 0.9 if ("rising" in p and "falling" in h) else 0.0} for p, h in pairs]

    m = asyncio.run(memory.state([a, b, c], "scooters in Bengaluru", embed=embed, judge=judge))
    assert [p["id"] for p in m["projects"]][:2] == ["r1", "r2"] and m["projects"][2]["relevance"] == 0
    assert m["recurring_claims"][0]["runs"] == ["r1", "r2"]
    assert m["entities"][0]["name"] == "Yulu" and m["entities"][0]["runs"] == ["r1", "r2"]
    assert len(m["contradictions"]) == 1 and m["open_questions"]
