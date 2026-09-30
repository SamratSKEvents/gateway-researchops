from backend.modules.belief import compute, cruxes

H = [{"id": "h1", "text": "demand exists", "prior": 0.5, "weight": 1, "favours": 1},
     {"id": "h2", "text": "regulation blocks it", "prior": 0.5, "weight": 1, "favours": -1}]


def ev(claim, cluster, h, stance, strength=1.0, rel=1.0, fr=1.0, domains=1):
    return {"claim": claim, "cluster": cluster, "hypothesis": h, "stance": stance, "strength": strength,
            "reliability": rel, "freshness": fr, "domains": domains}


def test_no_evidence_gives_prior_and_wide_range():
    r = compute(H, [], [])
    assert r["verdict"] == 0.5 and r["high"] - r["low"] > 0.3


def test_supporting_evidence_raises_and_narrows():
    r = compute(H, [], [ev("c1", "c1", "h1", 1), ev("c2", "c2", "h1", 1)])
    h1 = r["hypotheses"][0]
    assert h1["p"] > 0.8 and r["verdict"] > 0.6
    assert (h1["high"] - h1["low"]) < (compute(H, [], [])["hypotheses"][0]["high"] - compute(H, [], [])["hypotheses"][0]["low"])


def test_copies_in_one_cluster_count_once():
    one = compute(H, [], [ev("c1", "k", "h1", 1)])["hypotheses"][0]["p"]
    copies = compute(H, [], [ev(f"c{i}", "k", "h1", 1) for i in range(10)])["hypotheses"][0]["p"]
    assert one == copies


def test_bad_hypothesis_evidence_lowers_verdict_and_weak_sources_matter_less():
    strong = compute(H, [], [ev("c1", "c1", "h2", 1)])["verdict"]
    weak = compute(H, [], [ev("c1", "c1", "h2", 1, rel=0.3, fr=0.5)])["verdict"]
    assert strong < weak < 0.5


def test_what_if_assumption_moves_verdict_and_default_is_neutral():
    A = [{"id": "a1", "text": "riders pay monthly", "hypothesis": "h1", "p": 0.7, "p0": 0.7, "strength": 1}]
    assert compute(H, A, [])["verdict"] == 0.5
    assert compute(H, [dict(A[0], p=0.95)], [])["verdict"] > 0.5


def test_cruxes_rank_the_flipping_cluster_first():
    E = [ev("c1", "c1", "h1", 1, domains=4), ev("c2", "c2", "h1", -1, strength=0.8)]   # net positive; without c1 it turns negative
    top = cruxes(H, [], E, n=2)
    assert top[0]["id"] == "c1" and top[0]["flips"] and not top[1]["flips"]


def test_many_weak_generic_supports_saturate_instead_of_reaching_certainty():
    E = [ev(f"c{i}", f"c{i}", "h1", 1, strength=0.7, rel=0.5, fr=0.9) for i in range(40)]
    assert 0.6 < compute(H, [], E)["hypotheses"][0]["p"] < 0.85
