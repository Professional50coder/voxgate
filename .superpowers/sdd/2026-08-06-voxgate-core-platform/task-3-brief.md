### Task 3: Explainable scorecard engine

**Files:**
- Create: `src/voxgate/ml/scorecard.py`, `tests/test_scorecard.py`

**Interfaces:**
- Produces (all pydantic except `Feature`/`Scorecard` which are plain classes):
  - `FeatureContribution`: `feature: str`, `value: float`, `weight: float`, `contribution: float` (= value·weight).
  - `ScoreResult`: `probability: float`, `band: str` (`"low"|"medium"|"high"`), `contributions: list[FeatureContribution]`, `bias: float`.
  - `Feature(name: str, weight: float, extractor: Callable[[dict], float])` — extractor maps case fields+check context → x ∈ [0, 1].
  - `Scorecard(features: list[Feature], bias: float, low_threshold: float, high_threshold: float)` with `score(data: dict) -> ScoreResult`; `probability = sigmoid(bias + Σ wᵢ·xᵢ)`; band: `p < low` → low, `p < high` → medium, else high.

- [ ] **Step 1: Write the failing tests** — `tests/test_scorecard.py`

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scorecard.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/voxgate/ml/scorecard.py`**

```python
import math
from typing import Callable
from pydantic import BaseModel

class FeatureContribution(BaseModel):
    feature: str
    value: float
    weight: float
    contribution: float

class ScoreResult(BaseModel):
    probability: float
    band: str
    contributions: list[FeatureContribution]
    bias: float

class Feature:
    def __init__(self, name: str, weight: float, extractor: Callable[[dict], float]):
        self.name, self.weight, self.extractor = name, weight, extractor

class Scorecard:
    def __init__(self, features: list[Feature], bias: float,
                 low_threshold: float, high_threshold: float):
        self.features, self.bias = features, bias
        self.low_threshold, self.high_threshold = low_threshold, high_threshold

    def score(self, data: dict) -> ScoreResult:
        contribs = []
        total = self.bias
        for f in self.features:
            x = float(f.extractor(data))
            c = x * f.weight
            total += c
            contribs.append(FeatureContribution(
                feature=f.name, value=round(x, 4),
                weight=f.weight, contribution=round(c, 4)))
        p = 1.0 / (1.0 + math.exp(-total))
        band = "low" if p < self.low_threshold else \
               "medium" if p < self.high_threshold else "high"
        return ScoreResult(probability=round(p, 6), band=band,
                           contributions=contribs, bias=self.bias)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_scorecard.py -v`
Expected: 4 PASS

---

