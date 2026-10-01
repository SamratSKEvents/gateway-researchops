import asyncio
from backend.modules import economics as EC

SNAP = {"query": "scooter subscriptions", "claims": {"c1": {"id": "c1", "text": "Plans cost Rs 1,499 a month.", "prices": ["Rs 1,499"]}},
        "result": {}}


def test_extract_keeps_evidence_only_with_real_cites():
    async def llm(*a):
        return {"applicable": True, "currency": "INR", "params": [
            {"name": "price", "value": 1499, "low": 1299, "high": 1599, "basis": "evidence", "cites": ["[c1]"], "note": ""},
            {"name": "cac", "value": 900, "low": 600, "high": 1500, "basis": "evidence", "cites": ["c404"], "note": "fake cite"},
            {"name": "churn", "value": 0.08, "low": 0.12, "high": 0.05, "basis": "assumption", "cites": [], "note": "no data"}]}
    r = asyncio.run(EC.extract(SNAP, llm=llm))
    assert r["params"]["price"]["basis"] == "evidence" and r["params"]["price"]["cites"] == ["c1"]
    assert r["params"]["cac"]["basis"] == "assumption"                      # cited a claim that does not exist
    assert r["params"]["churn"]["low"] == 0.05 and r["params"]["churn"]["high"] == 0.12   # range re-ordered


def test_simulate_metrics_and_override():
    P = {"price": {"value": 1500, "low": 1300, "high": 1600, "basis": "evidence"},
         "variable_cost": {"value": 600, "low": 500, "high": 900, "basis": "assumption"},
         "cac": {"value": 1200, "low": 800, "high": 2000, "basis": "assumption"},
         "churn": {"value": 0.1, "low": 0.06, "high": 0.15, "basis": "assumption"}}
    r = EC.simulate(P)
    assert r["base"]["margin"] == 900 and abs(r["base"]["ltv"] - 9000) < 1e-6 and abs(r["base"]["payback_months"] - 1200 / 900) < 1e-3
    assert 0 < r["probabilities"]["ltv_cac_above_3"] <= 1 and r["assumed"] == ["variable_cost", "cac", "churn"]
    r2 = EC.simulate(P, {"price": 500})
    assert r2["base"]["margin"] == -100 and r2["probabilities"]["margin_positive"] < 0.5
    assert "missing" in EC.simulate({"price": P["price"]})["error"]
