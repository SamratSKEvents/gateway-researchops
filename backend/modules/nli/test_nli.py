from backend.modules.trial.verifier import nli_ruling
from backend.modules.belief.stance import nli_stance


def test_nli_ruling_thresholds():
    assert nli_ruling({"entail": 0.93, "neutral": 0.06, "contradict": 0.01}) == "supported"
    assert nli_ruling({"entail": 0.5, "neutral": 0.4, "contradict": 0.1}) == "partial"
    assert nli_ruling({"entail": 0.0, "neutral": 0.0, "contradict": 1.0}) == "unsupported"
    assert nli_ruling({"entail": 0.1, "neutral": 0.9, "contradict": 0.0}) == "unsupported"


def test_nli_stance_maps_entail_contradict_neutral():
    h, c = {"id": "h1"}, {"id": "c1"}
    assert nli_stance(h, c, {"entail": 0.9, "neutral": 0.05, "contradict": 0.05})["stance"] == 1
    assert nli_stance(h, c, {"entail": 0.1, "neutral": 0.1, "contradict": 0.8})["stance"] == -1
    assert nli_stance(h, c, {"entail": 0.2, "neutral": 0.7, "contradict": 0.1}) is None
