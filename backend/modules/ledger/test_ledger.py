import time
from backend.modules.ledger import cluster, find_conflicts, freshness, claim_year
from backend.modules.ledger.freshness import doc_year


def test_claim_year_prefers_latest_year_in_sentence_then_doc():
    assert claim_year("Revenue grew from 2019 to 2023.") == 2023
    assert claim_year("Revenue grew strongly.", 2021) == 2021
    assert claim_year("Plans start at ₹2,500 a month") is None           # 2,500 is not a year
    assert doc_year("Updated March 2024\nBody text 2019") == 2024


def test_prices_decay_faster_than_market_facts():
    now = time.mktime((2026, 7, 1, 0, 0, 0, 0, 0, -1))
    price, fact = freshness("fact", 2024, has_price=True, now=now), freshness("fact", 2024, now=now)
    assert price < fact < 1
    assert freshness("fact", 2026, now=now) > 0.9
    assert freshness("fact", None) == 0.6


def test_syndicated_copies_fold_into_one_cluster():
    pr = "Yulu raised 82 million dollars in a Series B round led by Magna International to expand its electric fleet"
    items = [("c1", pr), ("c2", pr + " in Bengaluru."), ("c3", "Reuters: " + pr), ("c4", "Bounce charges riders per minute for scooters.")]
    cl = cluster(items)
    assert cl["c1"] == cl["c2"] == cl["c3"] == "c1"
    assert cl["c4"] == "c4"


def test_conflicting_prices_are_found_but_not_within_a_cluster():
    claims = [{"id": "c1", "text": "Yulu subscription plan costs ₹2,499 per month.", "cluster": "c1", "source": "s1"},
              {"id": "c2", "text": "The Yulu monthly plan is priced at ₹3,999.", "cluster": "c2", "source": "s2"},
              {"id": "c3", "text": "Yulu subscription plan costs ₹2,499 per month in 2024.", "cluster": "c1", "source": "s3"},
              {"id": "c4", "text": "Bounce plan costs ₹2,600 per month.", "cluster": "c4", "source": "s4"}]
    out = find_conflicts(claims)
    assert [(c["a"], c["b"], c["subject"]) for c in out] == [("c1", "c2", "Yulu")]     # c3 is c1's copy: one conflict, not two


def test_model_numbers_generic_subjects_and_different_things_are_not_conflicts():
    filler = [{"id": f"x{i}", "text": f"Electric sales rose in Bengaluru {i}.", "cluster": f"x{i}", "source": f"t{i}"} for i in range(10)]
    claims = filler + [
        {"id": "c1", "text": "Electric Mp3 scooter price is ₹45,000.", "cluster": "c1", "source": "s1"},        # "Mp3" is not ₹3
        {"id": "c2", "text": "Electric scooter plan price is ₹60,000 in Bengaluru.", "cluster": "c2", "source": "s2"},  # only generic subjects shared
        {"id": "c3", "text": "Ola raised ₹2,763 crore in funding.", "cluster": "c3", "source": "s3"},
        {"id": "c4", "text": "Ola raised ₹5 crore in seed funding in 2017.", "cluster": "c4", "source": "s4"},   # 500x apart: different rounds
        {"id": "c5", "text": "TVS iQube starting price ₹1.03 Lakh.", "cluster": "c5", "source": "s5"},
        {"id": "c6", "text": "The TVS Jupiter price is ₹73,700.", "cluster": "c6", "source": "s6"}]          # same brand, different products
    assert find_conflicts(claims) == []


def test_agreeing_numbers_are_not_conflicts():
    claims = [{"id": "c1", "text": "Yulu plan costs ₹2,499 per month.", "cluster": "c1", "source": "s1"},
              {"id": "c2", "text": "Yulu plan price is ₹2,599.", "cluster": "c2", "source": "s2"}]
    assert find_conflicts(claims) == []


def test_cite_id_normalises_model_citation_styles():
    from backend.modules.ledger import cite_id
    assert [cite_id(x) for x in ("[c12]", "c12", "12", "[12]", "Exhibit 12", " C12 ")] == ["c12"] * 6
