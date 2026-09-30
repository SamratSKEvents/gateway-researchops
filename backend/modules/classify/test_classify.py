import asyncio
from unittest.mock import patch
from backend.modules import classify


def run(c):
    return asyncio.run(c)


def test_llm_fallback_labels_and_uniform_on_failure():
    async def llm(task, system, user, schema, mt):
        return {"labels": [{"i": 0, "label": "b"}]}          # index 1 skipped by the model
    with patch.object(classify.nli, "available", return_value=False):
        out = run(classify.labels(["x", "y"], {"a": "A", "b": "B"}, llm=llm))
    assert out[0] == {"a": 0.0, "b": 1.0} and out[1] == {"a": 0.5, "b": 0.5}


def test_nli_scores_are_normalised_across_choices():
    async def judge(pairs):
        return [{"entail": 0.9 if h == "A" else 0.1, "neutral": 0, "contradict": 0} for _, h in pairs]
    with patch.object(classify.nli, "available", return_value=True), patch.object(classify.nli, "judge", judge):
        (d,) = run(classify.labels(["t"], {"a": "A", "b": "B"}))
        (k, p), = run(classify.best(["t"], {"a": "A", "b": "B"}))
    assert abs(d["a"] - 0.9) < 1e-6 and k == "a" and p > 0.8
