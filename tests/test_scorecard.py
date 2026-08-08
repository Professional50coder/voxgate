import math
from voxgate.ml.scorecard import Feature, Scorecard

def make_card():
    return Scorecard(
        features=[
            Feature("risk_a", 2.0, lambda d: d["a"]),
            Feature("risk_b", 1.0, lambda d: d["b"]),
        ],
        bias=-2.0, low_threshold=0.30, high_threshold=0.65)

def test_probability_matches_formula_and_is_deterministic():
    card = make_card()
    r1, r2 = card.score({"a": 0.5, "b": 1.0}), card.score({"a": 0.5, "b": 1.0})
    expected = 1 / (1 + math.exp(-(-2.0 + 2.0 * 0.5 + 1.0 * 1.0)))
    assert abs(r1.probability - expected) < 1e-9
    assert r1.probability == r2.probability

def test_contributions_are_attributable():
    r = make_card().score({"a": 0.5, "b": 1.0})
    by = {c.feature: c for c in r.contributions}
    assert by["risk_a"].contribution == 1.0 and by["risk_b"].contribution == 1.0
    assert r.bias == -2.0

def test_monotonic_increasing_risk_never_lowers_probability():
    card = make_card()
    p_low = card.score({"a": 0.0, "b": 0.2}).probability
    p_hi = card.score({"a": 1.0, "b": 0.2}).probability
    assert p_hi > p_low

def test_band_edges():
    card = make_card()
    assert card.score({"a": 0.0, "b": 0.0}).band == "low"      # p≈0.119
    assert card.score({"a": 0.5, "b": 1.0}).band == "medium"   # p=0.5
    assert card.score({"a": 1.0, "b": 1.0}).band == "high"     # p≈0.731
