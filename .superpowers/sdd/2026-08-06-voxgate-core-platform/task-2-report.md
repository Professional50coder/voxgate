# Task 2 Implementation Report

## Status: DONE

All TDD steps completed successfully. All 5 required tests pass. Full test suite (7 tests including pre-existing config tests) passes without regression.

## Files Created

1. `src/voxgate/ml/variants.py` - Transliteration variant expansion with normalization
2. `src/voxgate/ml/name_match.py` - Name matching ensemble with Jaro-Winkler, token_set, and optional embedding scores
3. `tests/test_name_match.py` - Five comprehensive test cases covering variants, strong/review/clear bands, aliases, and embedder renormalization

## Test Command & Full Output

```
uv run pytest tests/test_name_match.py -v
```

**Full Output:**

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate
configfile: pyproject.toml
plugins: anyio-4.14.2, langsmith-0.14.2
collected 5 items

tests/test_name_match.py::test_variants_cover_common_romanizations PASSED [ 20%]
tests/test_name_match.py::test_transliteration_variant_matches_strongly PASSED [ 40%]
tests/test_name_match.py::test_different_name_is_clear PASSED            [ 60%]
tests/test_name_match.py::test_alias_is_searched PASSED                  [ 80%]
tests/test_name_match.py::test_embedder_changes_score_and_renormalization_works PASSED [100%]

============================== 5 passed in 0.76s ==============================
```

## Full Suite (Regression Check)

All 7 tests (5 new + 2 pre-existing config tests) pass:

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate
configfile: pyproject.toml
plugins: anyio-4.14.2, langsmith-0.14.2
collected 7 items

tests/test_config.py::test_defaults PASSED                               [ 14%]
tests/test_config.py::test_env_override PASSED                           [ 28%]
tests/test_name_match.py::test_variants_cover_common_romanizations PASSED [ 42%]
tests/test_name_match.py::test_transliteration_variant_matches_strongly PASSED [ 57%]
tests/test_name_match.py::test_different_name_is_clear PASSED            [ 71%]
tests/test_name_match.py::test_alias_is_searched PASSED                  [ 85%]
tests/test_name_match.py::test_embedder_changes_score_and_renormalization_works PASSED [100%]

============================== 7 passed in 0.18s ==============================
```

## Implementation Details

### variants.py
- `_norm(name: str)` normalizes input: lowercase, strip diacritics via regex, normalize "al-" prefix to "al " spacing
- `_VARIANTS` dict maps 8 canonical Arabic name tokens to their romanization variants
- `_CANON` reverse mapping enables canonicalization during expansion
- `expand_variants(name: str)` returns sorted list of all valid romanization combinations (base + canonical + one-substitution variants)

**Example:** `"Muhammad Al-Rashid"` expands to include `"mohammed al rashid"` (normalized base), and variants like `"mohammad al rashid"`, `"muhammad al rasheed"`, etc.

### name_match.py
- `MatchCandidate(BaseModel)` holds all scoring components and band classification
- `_band(score)` classifies: ≥0.85 → "strong", ≥0.65 → "review", else "clear"
- `NameMatcher.match()` implements ensemble scoring:
  - Computes variant-aware matching over all query variants and entry aliases
  - Tracks best (jw, token_set, embedding_sim) tuple per entry
  - Applies ensemble formula: 0.35*jw + 0.25*ts + 0.40*emb (or renormalized 0.58*jw + 0.42*ts if embedder=None)
  - Applies DOB exact match boost +0.07 and nationality match boost +0.03 (capped at 1.0)
  - Returns top_k results sorted by combined score descending

### Key Validations from Tests
1. **test_transliteration_variant_matches_strongly**: "Muhammad Al-Rashid" matches "Mohammed Al Rashid" (UN-001) with combined > 0.9 and "strong" band
   - JW + token_set on normalized variants exceed 0.85 threshold
   - DOB + nationality boosts push it to ~0.95
2. **test_embedder_changes_score_and_renormalization_works**: Without embedder, exact name match ("Dmitri Volkov") still hits "strong" via 0.58*jw + 0.42*ts renormalization
3. **test_alias_is_searched**: Alias "Abu Khalid" found in entry aliases, hits "review" or higher band

## Deviations from Brief

None. All specifications implemented exactly:
- Ensemble weights: 0.35*jw + 0.25*ts + 0.40*emb ✓
- Renormalization without embedder: 0.58*jw + 0.42*ts ✓
- Band thresholds: 0.85 (strong), 0.65 (review), else clear ✓
- DOB boost +0.07, nationality boost +0.03 ✓
- Cap at 1.0 ✓
- Aliases searched ✓
- Optional embedder support with proper handling ✓

## Concerns

None. The strong-match test passes with combined score > 0.9 without requiring any fixes to `_norm` handling. The normalization and variant expansion correctly handle the "Al-Rashid" → "al rashid" case, meeting the 0.9 bound requirement stated in the brief's Step 5 note.

---
**Completed:** 2026-08-06
**TDD Flow:** Tests → Verify Failure → Implement → Verify Pass ✓
