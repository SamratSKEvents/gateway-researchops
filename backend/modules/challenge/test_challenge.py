import asyncio
from unittest.mock import patch
from backend.modules import challenge as CH


def run(c):
    return asyncio.run(c)


def test_rule_thresholds():
    assert CH.rule(0.9, 0.0, 1.0) == "SUPPORTED"
    assert CH.rule(0.1, 0.9, 1.0) == "CONTRADICTED"
    assert CH.rule(0.1, 0.9, 0.3) == "OUTDATED"
    assert CH.rule(0.5, 0.1, 1.0) == "PARTIALLY_SUPPORTED"
    assert CH.rule(0.1, 0.1, 1.0) == "INSUFFICIENT_EVIDENCE"


def test_run_challenges_verifies_and_skips_same_domain():
    targets = [{"id": "c1", "text": "Yulu charges Rs 1,499 per month.", "domain": "yulu.bike", "year": 2024, "freshness": 0.9}]

    async def llm(task, system, user, schema, mt):
        return {"challenges": [{"id": "c1", "argument": "Price may be outdated.", "severity": "HIGH",
                                "requested_action": "Check current price.", "query": "yulu monthly price"}]}

    async def search(q):
        return [{"url": "https://yulu.bike/pricing", "title": "own site"},
                {"url": "https://news.example.com/yulu", "title": "News", "snippet": ""}]

    async def fetch(url):
        return "Yulu's monthly plan costs Rs 1,499 in Bengaluru. The weather was fine."

    async def judge(pairs):
        return [{"entail": 0.92 if "1,499" in p else 0.01, "neutral": 0, "contradict": 0.01} for p, _ in pairs]

    async def types(texts, choices):
        return [("FACT", 0.8) for _ in texts]

    with patch.object(CH.classify, "best", types), patch.object(CH.nli, "available", return_value=True):
        (r,) = run(CH.run(targets, search, fetch, judge=judge, llm=llm))
    assert r["status"] == "SUPPORTED" and r["claim_type"] == "FACT" and r["severity"] == "HIGH"
    assert r["evidence"] and all("yulu.bike" not in e["url"] for e in r["evidence"])


def test_no_pages_is_insufficient():
    async def llm(*a):
        return {"challenges": []}          # model skipped it -> default challenge

    async def search(q):
        return []

    async def types(texts, choices):
        return [("OPINION", 0.6) for _ in texts]

    with patch.object(CH.classify, "best", types):
        (r,) = run(CH.run([{"id": "c9", "text": "x", "domain": "a.com"}], search, lambda u: None, llm=llm))
    assert r["status"] == "INSUFFICIENT_EVIDENCE" and r["argument"]
