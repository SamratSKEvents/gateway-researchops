import asyncio
from unittest.mock import patch
from backend.modules import court


def test_hearing_uses_entailment_exhibits_and_drops_invalid_cites():
    snap = {"claims": {
        "c1": {"id": "c1", "text": "Yulu charges Rs 1,499 a month.", "source": "s1", "tasks": ["t1"], "cluster": "k1"},
        "c2": {"id": "c2", "text": "Yulu's plan is Rs 1,499 monthly.", "source": "s2", "tasks": ["t1"], "cluster": "k2"},
        "c3": {"id": "c3", "text": "Yulu's plan costs Rs 3,000 monthly.", "source": "s2", "tasks": ["t1"], "cluster": "k3"},
        "c4": {"id": "c4", "text": "The weather is nice.", "source": "s2", "tasks": ["t1"], "cluster": "k4"}},
        "sources": {"s1": {"domain": "a.com"}, "s2": {"domain": "b.com"}}, "result": {}}

    async def judge(pairs):
        return [{"entail": 0.9 if "1,499" in p else 0.0, "neutral": 0, "contradict": 0.8 if "3,000" in p else 0.0} for p, _ in pairs]

    async def llm(task, system, user, schema, mt):
        return {"turns": [{"role": "JUDGE", "statement": "Court opens.", "cites": []},
                          {"role": "PROSECUTION", "statement": "A source says 3,000.", "cites": ["c3", "c99"]},
                          {"role": "DEFENSE", "statement": "Another source confirms 1,499.", "cites": ["[c2]"]}],
                "ruling": "QUALIFIED", "rationale": "Sources disagree."}

    async def verify(stmts, claims):
        return {s["id"]: {"ruling": "supported", "reason": "", "by": "test"} for s in stmts}

    with patch.object(court.trial, "verify", verify):
        r = asyncio.run(court.hold("c1", snap, judge=judge, llm=llm))
    rel = {e["id"]: e["relation"] for e in r["exhibits"]}
    assert rel == {"c1": "claim under trial", "c2": "supports", "c3": "contradicts"}
    assert r["turns"][1]["cites"] == ["c3"] and r["turns"][1]["invalid_cites"] == ["c99"]
    assert r["turns"][2]["cites"] == ["c2"] and r["turns"][2]["verification"]["ruling"] == "supported"
    assert r["ruling"] == "QUALIFIED"
