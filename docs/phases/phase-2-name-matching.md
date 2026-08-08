# Phase 2 — Transliteration Variants + Name-Matching Ensemble

**Status:** ✅ Built & review-approved

## 1. Purpose

The `kyc-uae` pack's core AI/ML story (per the design spec §4.1) is Gulf-compliance name screening: Arabic names romanize multiple ways (Mohammed/Muhammad/Mohamed/Mohd), and naive string matching against sanctions/PEP lists misses these variants entirely. Phase 2 builds the reusable matching engine — independent of any pack — that later phases (Phase 5's `checks.py`) wire against real mock sanctions/PEP data. It sits in `src/voxgate/ml`, the platform's shared machine-learning layer, so any future pack can reuse it for its own screening needs.

## 2. What was built

| File | Responsibility |
|---|---|
| `src/voxgate/ml/variants.py` | Curated Arabic-name romanization variant table + `expand_variants()` |
| `src/voxgate/ml/name_match.py` | `MatchCandidate` pydantic model, `NameMatcher` ensemble matcher |
| `tests/test_name_match.py` | 5 tests covering variant expansion, strong/clear bands, alias search, embedder on/off |

## 3. Public interfaces

```python
# src/voxgate/ml/variants.py
def expand_variants(name: str) -> list[str]: ...   # includes normalized input + one-substitution variants

# src/voxgate/ml/name_match.py
class MatchCandidate(BaseModel):
    entry_id: str
    entry_name: str
    list_name: str
    jaro_winkler: float
    token_set: float
    embedding_sim: float | None
    combined: float
    band: str                      # "clear" | "review" | "strong"

class NameMatcher:
    def __init__(self, entries: list[dict], embedder: Callable | None = None): ...
    def match(self, name, dob=None, nationality=None, top_k=5) -> list[MatchCandidate]: ...
```

- `entries` carry `id, name, list, dob, nationality, aliases`.
- Bands: `combined >= 0.85` → `"strong"`; `>= 0.65` → `"review"`; else `"clear"`.

## 4. Key design decisions & why

- **Ensemble weights change shape when `embedder=None`.** With an embedder: `0.35·jw + 0.25·token_set + 0.40·emb`. Without one: renormalized to `0.58·jw + 0.42·token_set` — the embedding weight (0.40) is redistributed proportionally over the remaining two (0.35/0.60 ≈ 0.583, 0.25/0.60 ≈ 0.417), not simply dropped. This is the global constraint "Embeddings are optional everywhere … weights renormalize" made concrete. `sentence-transformers` is an optional extra (`pyproject.toml`'s `[project.optional-dependencies].embeddings`) and is never imported at module top level in `name_match.py` — the embedder is injected as a plain `Callable`, so the module has zero hard dependency on any embedding library.
- **Curated variant table, not a general transliteration algorithm.** `_VARIANTS` in `variants.py` hand-maps 8 canonical Arabic tokens (mohammed, abdul, hussein, rashid, said, aisha, khalid, jamal) to their common romanizations. A general phonetic algorithm would be more "correct" but far less predictable/testable for a portfolio-grade demo — the brief explicitly asks for "curated, extend freely."
- **One substitution at a time in `expand_variants`.** For each token position, only that token is swapped for a variant, holding the rest of the name fixed — avoids combinatorial explosion across multi-token names while still covering the realistic single-word substitution case (e.g. "Mohammed" → "Muhammad" but the rest of the name unchanged).
- **DOB/nationality boosts are additive corroboration signals, not part of the weighted ensemble.** `+0.07` for exact DOB match, `+0.03` for exact nationality match, applied after the weighted `combined` score and capped at `1.0`. This keeps the fuzzy-name-similarity core mathematically separate from corroborating structured data — a name-only match can never exceed what the ensemble computes, but corroborating facts can push a borderline match over a band threshold.
- **`NameMatcher` re-derives best-candidate selection using the *unrounded* weighted score inline** (`if score > 0.35*best[0] + 0.25*best[1] + 0.40*(best[2] or 0.0)`), not the final renormalized `combined` used for output — see review finding below.

## 5. Test evidence

From `task-2-report.md` — 5/5 passed (`tests/test_name_match.py`):

```
test_variants_cover_common_romanizations PASSED
test_transliteration_variant_matches_strongly PASSED
test_different_name_is_clear PASSED
test_alias_is_searched PASSED
test_embedder_changes_score_and_renormalization_works PASSED
5 passed in 0.76s
```

- `test_variants_cover_common_romanizations` — `expand_variants("Muhammad Al-Rashid")` includes `"mohammed al rashid"`.
- `test_transliteration_variant_matches_strongly` — `"Muhammad Al-Rashid"` matched with DOB `1975-03-02` and nationality `SY` against a two-entry list ranks `UN-001` first with `band == "strong"` and `combined > 0.9`.
- `test_different_name_is_clear` — an unrelated name (`"Priya Raghavan"`) never bands above `"clear"` against the same list.
- `test_alias_is_searched` — searching the alias `"Abu Khalid"` still surfaces `UN-001` (whose primary name is `"Mohammed Al Rashid"`) at `band != "clear"`.
- `test_embedder_changes_score_and_renormalization_works` — with a fake embedder, `embedding_sim is not None`; without one, `embedding_sim is None` and an exact-name match (`"Dmitri Volkov"`) still reaches `"strong"` via the renormalized weights alone.

Re-verified: `uv run pytest tests/test_name_match.py -q` → 5 passed (bundled in the 20-test Phase 1–5 run).

## 6. Review history

Per the ledger:

> Task 2: minor (deferred): best-pair selection uses embed-weights even without embedder; `_norm` private import; no boost-cap test
> Task 2: complete (no-git mode, review clean)

Three deferred minors, none blocking:
1. The per-candidate "best target" selection inside `match()` always scores using the full embed-weighted formula (`0.35·jw + 0.25·ts + 0.40·emb`) even when `embedder is None` (where `emb` is `0.0` throughout) — so the *selection* of which target/query pair is "best" is made under the embed-weighted formula, while the *final reported* `combined` score for that same pair uses the renormalized no-embedder formula. Functionally the two formulas are monotonically related when `emb=0` for all candidates, so it doesn't change which pair wins, but it's an inconsistency worth flagging if the formulas ever diverge.
2. `name_match.py` imports `_norm` from `variants.py`, a leading-underscore ("private") name — works but is an implicit contract between modules.
3. No dedicated test asserts the DOB/nationality boost is capped at `1.0` (only that it applies).

No report deviations recorded.

## 7. Dependencies

- **Consumes:** `rapidfuzz` (`fuzz.token_set_ratio`, `JaroWinkler.normalized_similarity`), `numpy` (cosine similarity when an embedder is supplied). No dependency on other VoxGate phases.
- **Feeds:** Phase 5 (`packs/kyc_uae/checks.py` instantiates `NameMatcher(entries)` per screening call, embedder left `None` in Plan 1).
