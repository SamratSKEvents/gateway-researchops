import asyncio
from backend.modules.trial import hold, verify, ROLES

LEDGER = [{"id": "c1", "text": "Yulu charges ₹2,499 per month for its scooter plan.", "source_type": "News", "domain": "a.com", "year": 2025},
          {"id": "c2", "text": "Bounce shut down its subscription service in 2023.", "source_type": "News", "domain": "b.com", "year": 2023}]
CLAIMS = {c["id"]: c["text"] for c in LEDGER}


def test_every_role_speaks_invalid_cites_removed_challenger_hears_advocate():
    seen = {}

    async def llm(task, system, user, schema, max_tokens):
        seen[task] = user
        if task == "trial.market":
            raise RuntimeError("down")
        return {"points": [{"point": "Prices leave room.", "cites": ["c1", "c77"]}]}
    out = asyncio.run(hold("Launch?", "55%", LEDGER, llm))
    assert [r["role"] for r in out] == list(ROLES)
    adv = out[0]["points"][0]
    assert adv["cites"] == ["c1"] and adv["invalid_cites"] == ["c77"]
    assert "THE ADVOCATE ARGUED" in seen["trial.challenger"]
    assert next(r for r in out if r["role"] == "market")["error"]


def test_verifier_rules_without_llm_when_nothing_to_check():
    async def never(*a):
        raise AssertionError("should not call the model")
    r = asyncio.run(verify([{"id": "s1", "text": "Demand is huge.", "cites": []},
                            {"id": "s2", "text": "Regulators love drones.", "cites": ["c1"]}], CLAIMS, never))
    assert r["s1"]["ruling"] == r["s2"]["ruling"] == "unsupported"


def test_verifier_uses_model_ruling_and_marks_unchecked_on_failure():
    async def llm(*a):
        return {"rulings": [{"id": "s1", "ruling": "supported", "reason": "quote states price"}]}
    st = [{"id": "s1", "text": "Yulu plan costs ₹2,499 per month.", "cites": ["c1"]}]
    assert asyncio.run(verify(st, CLAIMS, llm))["s1"]["ruling"] == "supported"

    async def down(*a):
        raise RuntimeError
    assert asyncio.run(verify(st, CLAIMS, down))["s1"]["ruling"] == "unchecked"


def test_verifier_re_asks_statements_the_model_skipped_in_a_batch():
    calls = []

    async def llm(task, system, user, schema, max_tokens):
        calls.append(user)
        return {"rulings": [{"id": "s1", "ruling": "supported", "reason": ""}]} if "STATEMENT s1" in user else \
               {"rulings": [{"id": "s2", "ruling": "partial", "reason": ""}]}
    st = [{"id": "s1", "text": "Yulu plan costs ₹2,499.", "cites": ["c1"]}, {"id": "s2", "text": "Bounce shut down in 2023.", "cites": ["c2"]}]
    r = asyncio.run(verify(st, CLAIMS, llm))
    assert (r["s1"]["ruling"], r["s2"]["ruling"]) == ("supported", "partial") and len(calls) == 2
