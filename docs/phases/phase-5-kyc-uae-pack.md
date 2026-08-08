# Phase 5 — The `kyc-uae` Pack + Shared Conformance Suite

**Status:** ✅ Built & review-approved

## 1. Purpose

Phase 5 is where the platform stops being abstract: it builds VoxGate's first real scenario pack — UAE fintech KYC onboarding, per the design spec's flagship `kyc-uae` pack (§2) — using every primitive from Phases 2–4 (`NameMatcher`, `Feature`/`Scorecard`, the `Pack` module contract). It also produces `tests/pack_conformance.py::run_conformance`, the generic contract-verification suite every future pack (including v2's `loan-intake`, `claim-fnol`, `realestate-aml`, `patient-intake`) must pass — this is the mechanism that actually enforces the "adding a pack touches no platform code" claim, not just an assertion of it.

## 2. What was built

| File | Responsibility |
|---|---|
| `packs/kyc_uae/pack.yaml` | `pack_id: kyc-uae`, display name, gate role `Compliance Officer`, thresholds `{low: 0.30, high: 0.65}` |
| `packs/kyc_uae/prompt.md` | ~190-word voice-interview system prompt |
| `packs/kyc_uae/schema.py` | `Schema` (6 fields) + 5 field validators + `REASK_HINTS` |
| `packs/kyc_uae/checks.py` | `sanctions_screen`, `pep_screen`, `adverse_media`, `CHECKS`, module-level `COUNTRIES` dict |
| `packs/kyc_uae/scoring.py` | `build_scorecard(low, high)` — 7 `Feature`s — and `FEATURE_FIELD_HINTS` |
| `packs/kyc_uae/data/sanctions.json` | 9 synthetic entries: UN Consolidated, OFAC SDN, UAE Local Terrorist List |
| `packs/kyc_uae/data/peps.json` | 5 synthetic `"list": "PEP"` entries |
| `packs/kyc_uae/data/adverse_media.json` | 3 synthetic name/headline/severity entries |
| `packs/kyc_uae/data/countries.json` | 13 synthetic countries across all 3 FATF tiers |
| `tests/pack_conformance.py` | `run_conformance(pack, valid_fields) -> None` — generic contract check, no `test_` prefix (not collected directly) |
| `tests/test_pack_kyc_uae.py` | 4 tests: conformance, clean-applicant-scores-low, sanctioned-lookalike-hits-high, schema-rejects-implausible |

## 3. Public interfaces

```python
# packs/kyc_uae/schema.py
class Schema(BaseModel):
    full_name: str
    dob: str                      # ISO date string, validated 18–100 years old
    nationality: str              # ISO alpha-2
    residency_status: str         # "uae_resident" | "non_resident"
    source_of_funds: str          # one of 6 categories
    product: str                  # "spot_trading" | "derivatives" | "custody"
REASK_HINTS: dict[str, str]       # one hint per field, all 6 covered

# packs/kyc_uae/checks.py
COUNTRIES: dict                   # loaded from data/countries.json, keyed by ISO alpha-2
def sanctions_screen(fields: dict) -> CheckResult: ...
def pep_screen(fields: dict) -> CheckResult: ...
def adverse_media(fields: dict) -> CheckResult: ...
CHECKS = [sanctions_screen, pep_screen, adverse_media]

# packs/kyc_uae/scoring.py
def build_scorecard(low, high) -> Scorecard: ...   # 7 features, bias=-3.5
FEATURE_FIELD_HINTS: dict[str, str]                 # every feature name -> a Schema field

# tests/pack_conformance.py
def run_conformance(pack: Pack, valid_fields: dict) -> None: ...   # raises AssertionError on violation
```

Scorecard features (weights): `fatf_nationality_risk` (2.2), `pep_similarity` (1.8), `sanctions_similarity` (3.0, the dominant weight), `adverse_media` (1.0), `source_of_funds_risk` (1.5), `product_risk` (0.8), `non_resident` (0.6). Bias `-3.5`.

## 4. Key design decisions & why

- **`nationality` FATF-tier validity is checked in `checks.py`-adjacent code (the `COUNTRIES` dict feeding `scoring.py`), not in `schema.py`.** The brief is explicit: "schema stays data-file-free" — `Schema`'s field validators only check structural/plausibility constraints (age range, name has 2+ tokens, enum membership) that don't require loading a JSON data file; risk-tier lookups belong to the scoring layer, which is inherently data-driven.
- **`scoring.py` reaches `checks.py`'s `COUNTRIES` via `sys.modules["voxgate_pack_kyc-uae_checks"].COUNTRIES`, not a relative import.** Because Phase 4's loader execs each pack file as a standalone module (not a package), `from .checks import COUNTRIES` has no parent package to resolve against and fails. The one-line comment left in `scoring.py` documents this explicitly: *"The loader … execs each pack file as a standalone module via importlib, not as a package, so `from .checks import COUNTRIES` fails (no parent package). It loads checks.py before scoring.py and registers it in sys.modules under this qualname, so we pull COUNTRIES from there instead."* This is only safe because of Phase 4's fixed `schema → checks → scoring` load order.
- **`_STATUS = {"strong": "hit", "review": "review", "clear": "clear"}` maps `NameMatcher` bands directly onto `CheckResult.status`.** A `"strong"` name match (≥0.85 combined) becomes a check `"hit"`; `NameMatcher`'s three-band vocabulary and `CheckResult`'s three-status vocabulary are deliberately the same cardinality so this mapping is a clean 1:1 relabeling, not a lossy compression.
- **`adverse_media` uses a flat `token_set_ratio > 85` threshold, not `NameMatcher`.** Adverse media hits are matched by simple fuzzy string similarity on the headline dataset (no DOB/nationality corroboration, no aliases) — a deliberately simpler check than sanctions/PEP screening, reflecting that adverse media hits are corroborating "soft" signal (feeds a `"review"` status only, never `"hit"`) rather than a hard sanctions match.
- **`sanctions_similarity` carries the highest scorecard weight (3.0) of any feature**, reflecting that a sanctions-list match is the single most severe risk signal in KYC — a deliberate design choice that the pack test `test_sanctioned_lookalike_hits_and_scores_high` exercises directly (a sanctioned-lookalike alone must push the score into `"high"` band).
- **`NameMatcher(entries)` is instantiated fresh, with `embedder=None`, on every single check call** (inside `_screen`, called per `sanctions_screen`/`pep_screen` invocation) rather than being built once and reused. Cheap for the current mock dataset sizes, but rebuilds the matcher (a no-op in the current implementation, since `NameMatcher.__init__` does no precomputation) on every case's every check — noted as a deferred efficiency minor, not a correctness issue.
- **Dataset entries were deliberately tuned, not copied verbatim from the brief's illustrative examples**, to control JaroWinkler noise against the fixed `CLEAN` test fixture (`"Priya Raghavan"`). The two entries the brief mandates verbatim — `UN-001 Mohammed Al Rashid` and `UAE-004 Khalid Bin Mahfouz` — are unchanged; the report documents the fix: initial filler names (e.g. "Farid Zaman", "Boris Ivanov") scored 0.53–0.59 against "Priya Raghavan" via baseline JaroWinkler noise, high enough to drag `CLEAN`'s scorecard probability into `"medium"` band. Per the brief's explicit instruction ("the fix is dataset/weights … never loosening the test"), filler names were re-picked for lower baseline resemblance, capping max sanctions match at 0.407 and max PEP match at 0.395 for `CLEAN`, landing its probability at ≈0.235 (solidly `"low"`). No scoring weights or test assertions were touched.
- **`pyproject.toml` gained `pythonpath = ["."]` under `[tool.pytest.ini_options]`.** Required because the brief's own test file does `from tests.pack_conformance import run_conformance`, and `uv run pytest` (unlike `python -m pytest`) doesn't add the repo root to `sys.path` by default absent a `tests/__init__.py` or `conftest.py`. Flagged explicitly in the report as a repo-wide config change outside the brief's stated file list, but a minimal, additive, standard pytest option — and the review confirmed it as necessary (see ledger).

## 5. Test evidence

From `task-5-report.md` — 4/4 passed (`tests/test_pack_kyc_uae.py`), 20/20 in the full suite at that point:

```
test_conformance PASSED
test_clean_applicant_scores_low PASSED
test_sanctioned_lookalike_hits_and_scores_high PASSED
test_schema_rejects_implausible PASSED
4 passed in 0.17s
```

```
uv run pytest -q
20 passed in 0.25s
```

- `test_conformance` — runs the generic `run_conformance(pack, CLEAN)` against the real `kyc-uae` pack: checks `pack.yaml` essentials, schema round-trip vs. `reask_hints` coverage, every check returns a valid `CheckResult`, the scorecard produces a valid band with ≥3 contributions, every scorecard feature maps to a re-askable schema field, and the prompt is substantive (>100 chars).
- `test_clean_applicant_scores_low` — the fixed `CLEAN` fixture (`Priya Raghavan`, salary, UAE resident, spot trading) scores `"clear"` on every individual check and `"low"` band overall — verifies each check is independently clean before checking the aggregate, per the report ("a real behavioral check, not a tautology").
- `test_sanctioned_lookalike_hits_and_scores_high` — the fixed `RISKY` fixture (`Muhammad Al-Rashid`, DOB `1975-03-02`, nationality `SY`, crypto trading, derivatives — a transliteration variant of `UN-001`, matching its DOB and nationality) triggers a sanctions `"hit"` against exactly `UN-001`, and the overall score reaches `"high"` band — proves the DOB+nationality corroboration boosts (Phase 2) actually push a variant name to the top rank and into the hit band.
- `test_schema_rejects_implausible` — three implausible payloads (age outside 18–100, single-token name, invalid `source_of_funds` enum value) each raise on `Schema(**bad)`.

Re-verified as part of this documentation pass: `uv run pytest tests/test_config.py tests/test_name_match.py tests/test_scorecard.py tests/test_pack_loader.py tests/test_pack_kyc_uae.py -q` → **20 passed** (matches the report's final count exactly).

## 6. Review history

Per the ledger:

> Task 5: minor (deferred): adverse_media/UAE-list data at exact brief minimum; NameMatcher rebuilt per check call; no adverse_media hit-path test; scoring.py hardcodes qualname "voxgate_pack_kyc-uae_checks" (renaming pack_id silently breaks it)
> Task 5: complete (no-git mode, review clean; pythonpath=["."] added to pyproject — reviewer confirmed necessary)

Four deferred minors:
1. `adverse_media.json` (3 entries) and the UAE Local Terrorist List slice of `sanctions.json` (2 entries) sit at the brief's exact stated minimums rather than exceeding them — thinner coverage than the sanctions/PEP lists overall.
2. `NameMatcher` is constructed fresh on every check call (see §4 above) rather than cached — a performance minor, not correctness.
3. No test exercises the `adverse_media` check's actual `"review"`-status hit path (i.e., a fixture whose name fuzzy-matches an `adverse_media.json` entry above the severity threshold) — the existing tests only exercise sanctions/PEP hit paths and the clean/no-hit path.
4. `scoring.py` hardcodes the sys.modules qualname string `"voxgate_pack_kyc-uae_checks"` — if the pack's `pack_id` in `pack.yaml` were ever renamed (loader derives the qualname from `pack_id`), this string would silently stop matching and `scoring.py` would raise a `KeyError` on import with no obvious link back to the rename, rather than failing loudly at the point of the actual mismatch.

Report deviations: dataset entity names diverge from the brief's illustrative examples (documented above); the `pythonpath` addition to `pyproject.toml` was outside the brief's stated file list but confirmed necessary by review.

## 7. Dependencies

- **Consumes:** Phase 2 (`NameMatcher`, used in `checks.py`), Phase 3 (`Feature`, `Scorecard`, used in `scoring.py`), Phase 4 (the full pack module contract — `load_pack`/`load_packs` load this exact directory).
- **Feeds:** Phase 6 (the graph's tests import `CLEAN`/`RISKY` fixtures directly from `tests.test_pack_kyc_uae` and build the graph against this loaded pack), Phase 7 (`CaseRunner` tests do the same), Phase 8 (API tests do the same), Phase 9 (integration test and demo script use `RISKY`/this pack). `tests/pack_conformance.py::run_conformance` is the contract every future pack (v2 roadmap: `loan-intake`, `claim-fnol`, `realestate-aml`, `patient-intake`) must pass.
