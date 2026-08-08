# Phase 1 — Project Scaffold + Settings

**Status:** ✅ Built & review-approved

## 1. Purpose

Every other phase depends on a working package layout and a single source of truth for runtime configuration (database DSN, packs directory). Phase 1 establishes that scaffold: the `pyproject.toml`/`uv` project, the `src/voxgate` package tree with empty subpackages for the pieces that later phases fill in (`ml`, `packs`, `graph`, `service`), and the `Settings` object every later phase reads instead of touching `os.environ` directly. It sits at the very base of the pipeline — nothing else in VoxGate can run without it.

## 2. What was built

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata, dependencies (`langgraph`, `langgraph-checkpoint-postgres`, `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `pyyaml`, `rapidfuzz`, `numpy`, `psycopg[binary]`), optional `embeddings` and `voice` extras, `dev` dependency group (`pytest`, `httpx`, `websockets`), hatchling build config, pytest config (`testpaths = ["tests"]`, later extended with `pythonpath = ["."]` in Phase 5) |
| `docker-compose.yml` | Single `postgres:16-alpine` service, port `5433`, credentials `voxgate`/`voxgate`, named volume `pgdata` |
| `.env.example` | Documents `VOXGATE_DATABASE_URL`; unset = in-memory dev mode |
| `src/voxgate/__init__.py` | Package marker |
| `src/voxgate/config.py` | `Settings` (pydantic-settings) + `get_settings()` |
| `src/voxgate/ml/__init__.py`, `src/voxgate/packs/__init__.py`, `src/voxgate/graph/__init__.py`, `src/voxgate/service/__init__.py` | Empty markers reserving the subpackages Phases 2–8 fill in |
| `tests/test_config.py` | `test_defaults`, `test_env_override` |

## 3. Public interfaces

```python
# src/voxgate/config.py
REPO_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOXGATE_", env_file=".env", extra="ignore")
    database_url: str | None = None
    packs_dir: Path = REPO_ROOT / "packs"

def get_settings() -> Settings: ...
```

- Env var `VOXGATE_DATABASE_URL` → `database_url` (default `None`, meaning in-memory checkpointer mode).
- Env var `VOXGATE_PACKS_DIR` → `packs_dir` (default `<repo root>/packs`, computed relative to the `config.py` file location, not the cwd).

## 4. Key design decisions & why

- **`database_url: str | None = None` as the in-memory/Postgres switch.** No separate "mode" flag — later phases (`create_app` in Phase 8) branch on `settings.database_url` truthiness to pick `MemorySaver` vs. a Postgres checkpointer factory. One field, one decision point.
- **`packs_dir` computed from `Path(__file__)`, not `Path.cwd()`.** Makes `Settings()` work identically regardless of the directory `pytest`/`uvicorn` is invoked from — important since the brief mandates `uv run …` from the repo root but nothing enforces that at runtime.
- **`extra="ignore"`.** Unrelated env vars (e.g. Postgres/Docker vars sharing a shell) don't raise validation errors.
- **Reserved-but-empty subpackages (`ml`, `packs`, `graph`, `service`) created in Phase 1.** Establishes the module layout the design spec's architecture maps onto up front, so Phases 2–8 only ever add files, never restructure packages.

## 5. Test evidence

From `task-1-report.md` — 2/2 passed:

```
tests/test_config.py::test_defaults PASSED
tests/test_config.py::test_env_override PASSED
2 passed in 0.74s
```

- `test_defaults` — with `VOXGATE_DATABASE_URL` unset, `Settings().database_url is None` and `packs_dir.name == "packs"`.
- `test_env_override` — setting `VOXGATE_DATABASE_URL` and `VOXGATE_PACKS_DIR` env vars is reflected in a fresh `Settings()` instance.

Re-verified as part of this documentation pass: `uv run pytest tests/test_config.py -q` → 2 passed (bundled with the other Phase 1–5 suites, 20 passed total, see Phase 5 doc).

## 6. Review history

Per the SDD ledger (`.superpowers/sdd/2026-08-06-voxgate-core-platform/progress.md`):

> Task 1: minor (deferred): `get_settings()` untested (named interface, test is import-only)
> Task 1: complete (no-git mode, review clean)

No fixes were required; the sole finding was deferred as a minor (the tests exercise `Settings()` directly, not the `get_settings()` wrapper function — functionally equivalent but not literally covered).

Report deviations: none recorded (`task-1-report.md`: "None. Implementation follows the brief exactly.").

## 7. Dependencies

- **Consumes:** nothing (root of the dependency graph).
- **Feeds:** every subsequent phase. Phase 4's `loader.load_packs()` and Phase 5's pack tests use `get_settings().packs_dir`; Phase 8's `create_app()` branches on `settings.database_url` to select the checkpointer.
