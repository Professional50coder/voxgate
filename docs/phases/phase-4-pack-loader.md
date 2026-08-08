# Phase 4 — Pack Protocols + Loader

**Status:** ✅ Built & review-approved

## 1. Purpose

VoxGate's central extensibility claim (design spec §2, "Adding a pack requires zero changes to platform code") depends on a formal contract between a pack directory on disk and the rest of the platform. Phase 4 defines that contract — the `Pack` dataclass and `CheckResult` model that platform code (graph, API, dashboard) programs against — and the `loader.py` that turns a `packs/<id>/` directory into a fully-wired `Pack` instance. It sits between the ML primitives (Phases 2–3) and the first real pack (Phase 5): nothing pack-specific lives here, only the generic loading/wiring machinery.

## 2. What was built

| File | Responsibility |
|---|---|
| `src/voxgate/packs/base.py` | `CheckResult` (pydantic), `Pack` (dataclass) — the platform-facing contract |
| `src/voxgate/packs/loader.py` | `PackLoadError`, `_load_module`, `load_pack`, `load_packs` |
| `tests/test_pack_loader.py` | 5 tests (2 original + 3 added in the fix round) against a throwaway "toy" pack built in `tmp_path` |

## 3. Public interfaces

```python
# src/voxgate/packs/base.py
class CheckResult(BaseModel):
    check_name: str
    status: str                 # "clear" | "review" | "hit"
    score: float
    details: dict

@dataclass
class Pack:
    pack_id: str
    display_name: str
    gate_role: str
    low_threshold: float
    high_threshold: float
    schema_model: type[BaseModel]
    reask_hints: dict[str, str]
    prompt: str
    checks: list[Callable[[dict], CheckResult]]
    scorecard: Scorecard
    feature_field_hints: dict[str, str]
    path: Path

# src/voxgate/packs/loader.py
class PackLoadError(Exception): ...
def load_pack(path: Path) -> Pack: ...
def load_packs(packs_dir: Path) -> dict[str, Pack]: ...   # skips non-dirs and dirs without pack.yaml
```

**Pack module contract** (what every pack directory must expose):

| Pack file | Must expose |
|---|---|
| `pack.yaml` | `pack_id`, `display_name`, `gate_role`, `thresholds: {low, high}` |
| `schema.py` | `Schema` (pydantic `BaseModel`), `REASK_HINTS: dict[str, str]` |
| `checks.py` | `CHECKS: list[Callable[[dict], CheckResult]]` |
| `scoring.py` | `build_scorecard(low: float, high: float) -> Scorecard`, `FEATURE_FIELD_HINTS: dict[str, str]` |
| `prompt.md` | Raw text, read verbatim into `Pack.prompt` |

## 4. Key design decisions & why

- **Pack files are loaded as standalone modules via `importlib.util.spec_from_file_location`, registered in `sys.modules` under a synthetic qualname (`voxgate_pack_{pack_id}_{schema|checks|scoring}`), not as a Python package.** This lets a pack directory live outside `src/` (at `packs/<id>/`, sibling to `src/`) with no `__init__.py`/package machinery, while still letting one pack file `import` another loaded pack file's globals via `sys.modules[qualname]` — the mechanism Phase 5's `scoring.py` relies on to reach `checks.py`'s `COUNTRIES` dict (see Phase 5 doc, "import caveat").
- **Load order is fixed: `schema.py` → `checks.py` → `scoring.py`.** `checks.py` is guaranteed to be in `sys.modules` before `scoring.py` executes, which is what makes the `sys.modules["voxgate_pack_kyc-uae_checks"].COUNTRIES` pattern in Phase 5 valid. The report explicitly calls this out as "critical module load order (checks before scoring)."
- **`PackLoadError` wraps every exception raised while loading a single pack**, added in the Task 4 fix round. `load_pack()`'s body is wrapped in `try/except Exception as e: raise PackLoadError(f"Failed to load pack from {path}: {e}") from e` — so a malformed `pack.yaml` (missing `thresholds`), a missing `scoring.py`, or any other failure surfaces with the pack's path in the message and the original exception preserved as `__cause__`, instead of a bare `KeyError`/`FileNotFoundError` with no context about *which* pack failed.
- **Duplicate `pack_id` across two directories raises `ValueError`**, also added in the fix round. `load_packs()` tracks a `pack_paths: dict[str, Path]` alongside the output dict; on a second pack declaring an already-seen `pack_id`, it raises `ValueError` naming both directories — closing the original silent-overwrite hole where the second pack's modules would clobber the first's entries in both the returned dict and `sys.modules`.
- **`load_packs` silently skips non-directories and directories without `pack.yaml`.** Lets a `packs/` directory contain a `README.md` or other scratch files without breaking the loader — enforced by `test_load_packs_skips_junk`.

## 5. Test evidence

From `task-4-report.md` (initial) and the fix report appended to `task-4-report.md` — final: 5/5 in `test_pack_loader.py`, 16/16 in the full suite at that point:

```
test_load_pack_wires_everything PASSED
test_load_packs_skips_junk PASSED
test_load_packs_detects_duplicate_pack_id PASSED
test_load_pack_missing_thresholds_raises_pack_load_error PASSED
test_load_pack_missing_scoring_py_raises_pack_load_error PASSED
5 passed in 0.32s
```

- `test_load_pack_wires_everything` — builds a throwaway "toy" pack in `tmp_path` and asserts every field of the returned `Pack` is correctly wired: `pack_id`, `gate_role`, thresholds, `schema_model` instantiation, `checks[0](...)` execution, `scorecard.score(...)` producing a valid band with contributions, `feature_field_hints`, and `prompt` content.
- `test_load_packs_skips_junk` — a non-pack directory and a stray file next to a valid pack don't break `load_packs`.
- `test_load_packs_detects_duplicate_pack_id` (added in fix round) — two pack directories declaring the same `pack_id` raise `ValueError` naming both directories.
- `test_load_pack_missing_thresholds_raises_pack_load_error` (added in fix round) — a `pack.yaml` without a `thresholds` key raises `PackLoadError` containing the pack path, with `__cause__` set.
- `test_load_pack_missing_scoring_py_raises_pack_load_error` (added in fix round) — a pack directory missing `scoring.py` raises `PackLoadError` similarly.

Re-verified: `uv run pytest tests/test_pack_loader.py -q` → 5 passed (bundled in the 20-test Phase 1–5 run, which additionally includes Phase 5's pack-conformance tests exercising the same loader against the real `kyc-uae` pack).

## 6. Review history

Per the ledger:

> Task 4: fix round 1/5 (2 addressed, 0 open — PackLoadError wrapping; duplicate pack_id ValueError)
> Task 4: minor (deferred): colliding pack's submodules land in sys.modules before the duplicate-id ValueError fires; duplicate-pack test's "pack1" assertion trivially satisfied by the quoted id
> Task 4: complete (no-git mode, review clean)

Both findings from the first review round were fixed (not deferred): the missing `PackLoadError` wrapping and the silent duplicate-`pack_id` overwrite. After the fix, two new minors were noted and deferred:
1. Even though `load_packs` now raises on a duplicate `pack_id`, the colliding pack's `schema`/`checks`/`scoring` submodules have already been `exec_module`'d and registered in `sys.modules` (under the *second* pack's qualname, which shares the same `pack_id`-derived string as the first) by the time the `ValueError` fires in `load_pack`'s wrapping call — so `sys.modules` retains stale/partial state after the error, a candidate for a v2 cleanup that isn't in scope here.
2. In `test_load_packs_detects_duplicate_pack_id`, the assertion `"pack1" in str(excinfo.value)` is trivially satisfied because the error message directly quotes the `pack_id` string (`'pack1'`), which happens to equal one of the directory names in the test fixture — a slightly weaker check than it first appears, though the accompanying `"pack2" in str(excinfo.value)` assertion (the *second* directory's actual name, distinct from its `pack_id`) does verify the second directory is genuinely named in the message.

Report deviations: none recorded in either the initial or fix report.

## 7. Dependencies

- **Consumes:** Phase 3's `Scorecard` (`base.py` imports `voxgate.ml.scorecard.Scorecard` for the `Pack.scorecard` field type).
- **Feeds:** Phase 5 (the `kyc-uae` pack is loaded through this exact `load_pack`/`load_packs` machinery), Phase 6 (graph built from a loaded `Pack`), Phase 7 (`CaseRunner` calls `load_packs` at startup).
