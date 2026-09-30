import asyncio
from unittest.mock import patch
from backend.modules import autopsy


def snap(**result):
    claims = {f"c{i}": {"id": f"c{i}", "text": f"claim {i} 40% of users", "source": "s1", "freshness": 0.3 if i < 3 else 0.9,
                        "cluster": f"k{i}", "cluster_domains": 1} for i in range(1, 7)}
    base = {"report": {"summary": [{"text": "s", "cites": list(claims)}], "verdict": {"label": "favourable", "p": 0.7, "low": 0.4, "high": 0.9},
                       "verification": {"statements": 10, "struck": 1, "partial": 0}, "hypotheses": [{"id": "h1", "text": "demand", "clusters": 1}]},
            "belief": {"cruxes": [{"kind": "assumption", "id": "a1", "text": "cheap servicing", "verdict_without": 0.4, "flips": True}],
                       "assumptions": [{"id": "a1"}]}, "challenges": [], "contradictions": []}
    base.update(result)
    return {"query": "q", "result": base, "claims": claims, "sources": {"s1": {"domain": "one.com", "type": "blog"}}}


def test_computed_findings_and_survival():
    async def best(texts, ch):
        return [("no_n", 0.8) for _ in texts]

    async def llm(*a):
        raise RuntimeError("down")

    with patch.object(autopsy.classify, "best", best):
        r = asyncio.run(autopsy.run(snap(), llm=llm))
    kinds = {f["auditor"] for f in r["findings"]}
    assert {"assumption", "temporal", "source", "data", "conclusion", "completeness"} <= kinds
    assert r["findings"][0]["severity"] == "CRITICAL" and r["survival"] in ("WEAKENED", "FAILS")
    assert any(x["flips"] for x in r["what_would_change"] if x["kind"] == "assumption")
    assert r["followups"] and all(f["question"] for f in r["followups"])


def test_llm_findings_keep_only_real_claim_ids():
    async def best(texts, ch):
        return [("none", 0.9) for _ in texts]

    async def llm(*a):
        return {"findings": [{"auditor": "logic", "title": "leap", "description": "d", "why_it_matters": "w", "severity": "LOW",
                              "claims": ["[c1]", "c404"], "recommended_action": "a", "needs_research": False}]}

    with patch.object(autopsy.classify, "best", best):
        r = asyncio.run(autopsy.run(snap(), llm=llm))
    (f,) = [f for f in r["findings"] if f["auditor"] == "logic"]
    assert f["claims"] == ["c1"]
