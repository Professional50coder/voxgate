# Task 5 Report: `kyc-uae` pack + shared conformance suite

## What I implemented

Followed the brief's 8 steps exactly. All new files live under `packs/kyc_uae/` at the
repo root (sibling of `src/`), confirmed against `Settings.packs_dir` default in
`src/voxgate/config.py` (`REPO_ROOT / "packs"`).

**Files created:**
- `packs/kyc_uae/data/sanctions.json` — 9 entries across UN Consolidated, OFAC SDN,
  and UAE Local Terrorist List. Includes the required `UN-001 Mohammed Al Rashid`
  (dob `1975-03-02`, SY, alias `Abu Khalid`), 3 OFAC SDN entries, 2 UAE Local
  Terrorist List entries. `"synthetic": true` at top level.
- `packs/kyc_uae/data/peps.json` — 5 `"list": "PEP"` entries. `"synthetic": true`.
- `packs/kyc_uae/data/adverse_media.json` — 3 entries with name/headline/severity.
  `"synthetic": true`.
- `packs/kyc_uae/data/countries.json` — 13 countries covering all three FATF tiers
  (clean: AE, IN, GB, US, SG, DE; grey: YE, RU, PK, SO; black: SY, KP, IR).
  `"synthetic": true`.
- `packs/kyc_uae/pack.yaml` — `pack_id: kyc-uae`, thresholds `{low: 0.30, high: 0.65}`,
  exactly as specified.
- `packs/kyc_uae/prompt.md` — ~190-word interview system prompt: compliance
  onboarding persona for a Dubai virtual-asset platform, collects the six schema
  fields one at a time, confirms name spelling, avoids legal advice, calls
  `record_field` / `complete_interview`.
- `packs/kyc_uae/schema.py` — verbatim from the brief (`Schema` + `REASK_HINTS`).
- `packs/kyc_uae/checks.py` — verbatim from the brief (`sanctions_screen`,
  `pep_screen`, `adverse_media`, `CHECKS`).
- `packs/kyc_uae/scoring.py` — verbatim from the brief's feature/weight table.
  Resolved the import caveat using the `sys.modules["voxgate_pack_kyc-uae_checks"]`
  route (per the ambiguity resolution), with a one-line comment explaining why the
  relative import can't work (loader execs each pack file as a standalone module,
  not a package) and that the loader guarantees `checks.py` loads before
  `scoring.py`.
- `tests/pack_conformance.py` — `run_conformance(pack, valid_fields)`, verbatim
  from the brief.
- `tests/test_pack_kyc_uae.py` — verbatim from the brief (`CLEAN`/`RISKY` fixtures,
  4 tests).

**Files changed:**
- `pyproject.toml` — added `pythonpath = ["."]` under `[tool.pytest.ini_options]`.
  Needed because the brief's test file does `from tests.pack_conformance import
  run_conformance`, which requires the repo root on `sys.path`; plain `uv run
  pytest` (unlike `python -m pytest`) doesn't add it by default with no
  `tests/__init__.py` and no conftest.py. This is a native pytest 7+ option
  (no new dependency) and is the minimal fix that keeps the brief's import
  exactly as written.

## Dataset tuning (Step 8 iteration)

First run: `test_sanctioned_lookalike_hits_and_scores_high` passed immediately
(RISKY reached `high` comfortably — sanctions contribution alone was 3.0 at a
combined score of 1.0, fatf risk 2.2, well past threshold). But
`test_clean_applicant_scores_low` failed: CLEAN landed in `medium` (probability
≈0.404), because JaroWinkler baseline similarity between unrelated same-alphabet
names of similar length is inherently noisy (~0.4-0.6), and my first draft of
filler sanctions/PEP entries (e.g. "Farid Zaman", "Boris Ivanov") happened to
score 0.53-0.59 against "Priya Raghavan" — high enough (even while still under
the 0.65 "clear" band cutoff) to drag the weighted sum into `medium`.

Fix: per the brief's explicit guidance ("the fix is dataset/weights ... never
loosening the test"), I measured JaroWinkler/token-set scores of ~30 candidate
names against "Priya Raghavan" with a throwaway script and re-picked all filler
sanctions/PEP entries (keeping the two verbatim-required entries, `UN-001` and
`UAE-004`, unchanged) for names with lower baseline resemblance. This capped the
max sanctions match at 0.407 (from the required entries themselves) and max PEP
match at 0.395, bringing CLEAN's probability to ≈0.235 — solidly in `low`. Did
not touch the scoring weights or the test file.

## Tests run

```
uv run pytest tests/test_pack_kyc_uae.py -v
```
```
tests/test_pack_kyc_uae.py::test_conformance PASSED                      [ 25%]
tests/test_pack_kyc_uae.py::test_clean_applicant_scores_low PASSED       [ 50%]
tests/test_pack_kyc_uae.py::test_sanctioned_lookalike_hits_and_scores_high PASSED [ 75%]
tests/test_pack_kyc_uae.py::test_schema_rejects_implausible PASSED       [100%]

4 passed in 0.17s
```

Full suite:
```
uv run pytest -q
```
```
....................                                                     [100%]
20 passed in 0.25s
```
16 pre-existing tests (config, name_match, pack_loader, scorecard) + 4 new,
all green, no warnings.

## Self-review

- **Completeness**: all 8 brief steps done. `nationality` validity against
  `countries.json` correctly lives in `checks.py`-adjacent code (`COUNTRIES`
  dict used by `scoring.py`'s `fatf_nationality_risk` feature), not in the
  schema, per the brief's note.
- **Quality**: file responsibilities match the brief 1:1 (datasets / pack
  metadata / prompt / schema / checks / scoring / conformance / pack tests).
  The one deviation from the brief's literal code (dataset names) is
  documented above and was required to make the CLEAN test pass without
  loosening it.
- **Discipline**: no extra abstractions, no speculative generalization beyond
  what the brief specifies. Did not touch `load_pack`'s ordering (checks
  already loads before scoring, so no change needed there).
- **Testing**: `test_sanctioned_lookalike_hits_and_scores_high` verifies the
  DOB+nationality boost actually pushes `UN-001` to top rank and into the
  `hit` band; `test_clean_applicant_scores_low` verifies every check is
  independently `clear` before checking the aggregate band, so it's a real
  behavioral check, not a tautology. Output is pristine (no deprecation
  warnings, no stderr noise).

## Concerns

- The `pyproject.toml` `pythonpath = ["."]` addition is a repo-wide config
  change, not scoped to this pack. It was necessary to satisfy the brief's own
  test-file import (`from tests.pack_conformance import run_conformance`)
  under the mandated run command (`uv run pytest ...`, not `python -m
  pytest`). Flagging it explicitly since it's outside the file list named in
  the brief's "Files" section, though it's a one-line, additive, standard
  pytest option.
- Dataset entries diverge from the brief's illustrative names (e.g. renamed
  `UAE-009`/`UN-002`/`UN-003`/`UN-005`/`OFAC-12`/`OFAC-20`/all 5 PEP entries)
  to control JaroWinkler noise against the fixed `CLEAN` name. The two
  entries the brief mandates verbatim (`UN-001 Mohammed Al Rashid`, `UAE-004
  Khalid Bin Mahfouz`) are unchanged.
