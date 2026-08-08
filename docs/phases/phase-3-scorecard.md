# Phase 3 — Explainable Scorecard Engine

**Status:** ✅ Built & review-approved

## 1. Purpose

Per the design spec §4.2, every pack's risk decision must be explainable: "the reviewer sees *why* the score is 0.74." Phase 3 builds the generic additive log-odds scorecard machinery — pack-agnostic, reusable across `kyc-uae`, and any future pack — that turns a set of weighted feature extractors into a probability, a routing band, and a fully attributable per-feature breakdown. It is pure math with no I/O, sitting in `src/voxgate/ml` alongside the name matcher, and is consumed by every pack's `scoring.py` (Phase 4's pack contract) and by the graph's `score` node (Phase 6).

## 2. What was built

| File | Responsibility |
|---|---|
| `src/voxgate/ml/scorecard.py` | `FeatureContribution`, `ScoreResult` (pydantic); `Feature`, `Scorecard` (plain classes) |
| `tests/test_scorecard.py` | 4 tests: formula correctness/determinism, attributability, monotonicity, band edges |

## 3. Public interfaces

```python
class FeatureContribution(BaseModel):
    feature: str
    value: float
    weight: float
    contribution: float          # = value * weight

class ScoreResult(BaseModel):
    probability: float
    band: str                    # "low" | "medium" | "high"
    contributions: list[FeatureContribution]
    bias: float

class Feature:
    def __init__(self, name: str, weight: float, extractor: Callable[[dict], float]): ...

class Scorecard:
    def __init__(self, features: list[Feature], bias: float,
                 low_threshold: float, high_threshold: float): ...
    def score(self, data: dict) -> ScoreResult: ...
```

`score()` computes `probability = sigmoid(bias + Σ weight_i · extractor_i(data))`; band: `p < low_threshold` → `"low"`, `p < high_threshold` → `"medium"`, else `"high"`.

## 4. Key design decisions & why

- **`Feature`/`Scorecard` are plain classes; `FeatureContribution`/`ScoreResult` are pydantic models.** The former hold a `Callable` extractor, which pydantic cannot serialize/validate meaningfully; the latter are pure data returned to callers (and later, per the graph brief, `.model_dump()`'d into `CaseState`) — so only the output side needs pydantic's validation/serialization.
- **Extractors map `data: dict -> x ∈ [0, 1]`, not raw feature values.** Keeps every feature on a common scale so weights are directly comparable as "how much does maxing out this factor move the log-odds" — critical for the waterfall visualization the design spec's dashboard (§3.3) shows reviewers.
- **Thresholds are constructor parameters (`low_threshold`, `high_threshold`), never hard-coded in `scorecard.py`.** Per the global constraint "Scorecard routing thresholds come from `pack.yaml` … never hard-code them in platform code" — `Scorecard` itself has no opinion on what the thresholds are; Phase 4's `build_scorecard(low, high)` pack contract is where each pack's `pack.yaml` thresholds get threaded in.
- **Deterministic, monotonic, additive log-odds formula.** No randomness, no interaction terms — `test_monotonic_increasing_risk_never_lowers_probability` encodes this as a hard requirement: raising any single risk feature's extractor value can never lower the output probability, which is what makes the score defensible to a compliance reviewer.
- **Values and contributions are rounded (4 decimals) before being wrapped in the pydantic model; the summed `total` (bias + Σ contributions) used for the sigmoid is not rounded until the final probability (6 decimals).** This means the *reported* `contribution` field (`round(x,4) `× weight, effectively, since `x` itself feeds forward before rounding — see the exact code) is computed from the same unrounded `x` used in the sigmoid, but the *emitted* `value`/`contribution` fields are independently rounded for display. See review finding below — this is a known, deferred minor.

## 5. Test evidence

From `task-3-report.md` — 4/4 passed (`tests/test_scorecard.py`):

```
test_probability_matches_formula_and_is_deterministic PASSED
test_contributions_are_attributable PASSED
test_monotonic_increasing_risk_never_lowers_probability PASSED
test_band_edges PASSED
4 passed in 0.02s
```

- `test_probability_matches_formula_and_is_deterministic` — for `bias=-2.0`, weights `2.0`/`1.0`, inputs `a=0.5, b=1.0`, the computed probability matches `1/(1+exp(-(-2.0+2.0·0.5+1.0·1.0)))` to `1e-9`, and calling `score()` twice with identical input yields identical output (no hidden state/randomness).
- `test_contributions_are_attributable` — each `FeatureContribution.contribution` equals its `value * weight` exactly, and `ScoreResult.bias` echoes the constructor's bias.
- `test_monotonic_increasing_risk_never_lowers_probability` — raising feature `a` from `0.0` to `1.0` (holding `b` fixed) strictly increases probability.
- `test_band_edges` — `a=b=0.0` → `p≈0.119` → `"low"`; `a=0.5,b=1.0` → `p=0.5` → `"medium"`; `a=b=1.0` → `p≈0.731` → `"high"`, verified against `low_threshold=0.30, high_threshold=0.65`.

Re-verified: `uv run pytest tests/test_scorecard.py -q` → 4 passed (bundled in the 20-test Phase 1–5 run).

## 6. Review history

Per the ledger:

> Task 3: minor (deferred): contribution rounded from unrounded x, so emitted value·weight may differ at 4th decimal
> Task 3: complete (no-git mode, review clean)

Single deferred minor: because `value` and `contribution` are each independently `round(…, 4)`, a consumer recomputing `contribution` as `emitted_value * weight` off the *emitted* (already-rounded) `value` can get a result that differs from the emitted `contribution` at the 4th decimal place (since `contribution` was computed from the unrounded `x`, not the rounded `value`). Cosmetic — does not affect the probability, band, or the sum used for routing — deferred rather than fixed.

No report deviations recorded ("None. Implementation follows brief specification exactly...").

## 7. Dependencies

- **Consumes:** nothing beyond the standard library (`math.exp`) and `pydantic`. No dependency on other VoxGate phases.
- **Feeds:** Phase 4 (`Pack.scorecard: Scorecard` field, `base.py` imports `Scorecard`), Phase 5 (`packs/kyc_uae/scoring.py`'s `build_scorecard`), Phase 6 (graph's `score` node calls `pack.scorecard.score(...)`).
