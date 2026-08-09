# VoxGate Production Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert VoxGate's synchronous, in-memory backend into an async, Postgres-backed, tenant-aware service with a non-blocking run worker and SSE streaming — then scaffold a Next.js app against the endpoints that do not change.

**Architecture:** The LangGraph checkpointer stays the sole owner of case truth. A new `cases` table is a *projection* written by `_sync()`, never a second source of truth. Execution moves out of the request thread into a `RunWorker` (asyncio task per run, semaphore-bounded). Events move from an in-memory dict to Postgres `LISTEN`/`NOTIFY` with a `seq`-indexed table for `Last-Event-ID` replay. Store and bus are Protocols with in-memory and Postgres implementations, kept honest by one contract suite run against both.

**Tech Stack:** Python 3.12, LangGraph 1.2.10, FastAPI, psycopg 3 + psycopg_pool, sse-starlette, pytest-asyncio, Next.js 15 + TypeScript.

> **REFRESHED TWICE on 2026-08-07.** Work kept landing between authoring and
> execution. Everything in this list exists, is tested, and must survive:
>
> - `CORSMiddleware` in `app.py`
> - `POST /packs/{id}/extract`, `POST /packs/draft`, `POST /packs/publish`
> - `reask_hints` on `GET /packs`
> - `CaseRunner.checkpointer` (an attribute, retained so a pack published at
>   runtime can be compiled onto the same checkpointer)
> - modules `ml/groq_client.py`, `ml/extract.py`, `ml/authoring.py`,
>   `packs/emit.py`, `packs/publish.py`
> - `exa-py`, and the corrected voice extra
>
> Tasks 1, 7 and 9 were rewritten to preserve all of it. **If a task tells you
> to delete or replace something on that list, the task is stale: stop and say
> so rather than following it.**

**Spec:** `docs/superpowers/specs/2026-08-07-production-spine-design.md`
**Research:** `docs/research/2026-08-07-langgraph-production-upgrade.md`

## Global Constraints

- **Test suite must stay offline and keyless.** `uv run pytest -q` → **138 passed, 1 skipped** as of the refresh below, no Docker. Postgres tests are opt-in via `VOXGATE_TEST_DB`; Groq tests via a configured key. Both skip cleanly when unset. The count only ever goes up: if you see fewer than 138, something regressed.
- **`durability="sync"` at every `ainvoke`/`astream` site.** The LangGraph default is `"async"` and can lose the last checkpoint on a crash mid-step.
- **`thread_id = f"{tenant_id}:{case_id}"`.** Keep under 255 chars.
- **Never smuggle tenancy through `config["configurable"]`.** Use `context=RunContext(...)`. `config_schema` is deprecated with removal in v2.0.0.
- **`pg_notify` payloads must stay under 8000 bytes.** Notify with `{case_id, kind, seq}` only; the SSE handler reads the row.
- **Never open a Postgres connection per browser client.** One listener connection per worker process.
- **Graph topology is frozen this plan.** No subgraph extraction, no `Command` refactor — deferred to the voice sub-project.
- **Return 404, never 403,** for a case belonging to another tenant. 403 confirms existence.
- **All work on branch `feat/production-spine`.** Commit after every task.
- **Windows/PowerShell dev machine.** Always invoke through `uv run` from the repo root.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/voxgate/graph/context.py` | NEW — `RunContext` dataclass |
| `src/voxgate/graph/build.py` | MODIFY — `context_schema`, nodes take `runtime` |
| `src/voxgate/service/db.py` | NEW — pool + saver construction, schema DDL |
| `src/voxgate/service/store.py` | REWRITE — `CaseStore` Protocol, `InMemoryCaseStore`, `PgCaseStore` |
| `src/voxgate/service/events.py` | REWRITE — `EventBus` Protocol, `InMemoryEventBus`, `PgEventBus` |
| `src/voxgate/service/runs.py` | NEW — `RunStore` + `RunWorker` |
| `src/voxgate/service/runner.py` | REWRITE — async, delegates execution to `RunWorker` |
| `src/voxgate/service/app.py` | MODIFY — lifespan, tenant dep, 202 + `?wait=`, SSE |
| `tests/contracts/test_case_store.py` | NEW — contract suite, both store impls |
| `tests/contracts/test_event_bus.py` | NEW — contract suite, both bus impls |
| `tests/test_runs.py` | NEW — worker, multitask, orphan recovery |
| `apps/web/**` | NEW — Next.js scaffold |

---

## Task 1: Dependency pins and housekeeping

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/voxgate/service/app.py:4` (import), `src/voxgate/service/runner.py`
- Modify: `tests/test_runner.py`, `tests/test_graph.py`, `tests/test_graph_wave1.py` (import rename)

**Interfaces:**
- Consumes: nothing.
- Produces: correct dependency floors; `InMemorySaver` name used everywhere.

- [ ] **Step 1: Confirm the branch**

The branch already exists. Verify you are on it; do not create it again.

```bash
cd C:/Users/GAURAV/OneDrive/Desktop/PPC_Tech/voxgate
git rev-parse --abbrev-ref HEAD    # must print: feat/production-spine
```

- [ ] **Step 2: Raise only the dependency floors that are still stale**

> **Do NOT paste a replacement `dependencies` block.** The floors and the voice
> extra were already corrected, and `exa-py`, `groq` and `httpx` are now real
> dependencies. Replacing the block wholesale would delete them.
>
> Edit in place, and only these two lines:

```toml
# in [project] dependencies, raise these two floors:
"langgraph>=1.2.10,<2",                  # was: langgraph>=0.4
"langgraph-checkpoint-postgres>=3.1,<4", # was: langgraph-checkpoint-postgres>=2.0
```

Then **add** the three new runtime dependencies the spine needs, without
removing anything already present:

```toml
"psycopg[binary,pool]>=3.2",
"sse-starlette>=2.1",
```

Leave the `voice` and `embeddings` extras exactly as they are: the voice extra
was corrected earlier to `pipecat-ai[webrtc,websocket,whisper,kokoro,silero,groq]>=1.7,<2`
and reverting it would reintroduce two paid-key services.

- [ ] **Step 2b: Add the async test dependency**

`pytest-asyncio` is not yet installed. Add it to the dev group:

```bash
uv add --dev pytest-asyncio
```

- [ ] **Step 3: Add pytest-asyncio config**

In `pyproject.toml` under `[tool.pytest.ini_options]`, keep the existing `pythonpath = ["."]` and add:

```toml
asyncio_mode = "auto"
```

- [ ] **Step 4: Sync and confirm the suite is still green**

Run: `uv sync && uv run pytest -q`
Expected: `138 passed, 1 skipped` (or more)

- [ ] **Step 5: Rename `MemorySaver` → `InMemorySaver`**

`MemorySaver` is a backwards-compat alias as of 1.2.10 (`langgraph/checkpoint/memory/__init__.py:631`). In `src/voxgate/service/app.py` change:

```python
from langgraph.checkpoint.memory import InMemorySaver
```

and the factory reference `else MemorySaver` → `else InMemorySaver`. Apply the same rename in `tests/test_runner.py`, `tests/test_graph.py`, `tests/test_graph_wave1.py`.

- [ ] **Step 6: Verify**

Run: `uv run pytest -q`
Expected: `138 passed, 1 skipped` (or more)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src tests
git commit -m "chore: raise dependency floors, rename MemorySaver, enable asyncio mode"
```

---

## Task 2: RunContext

**Files:**
- Create: `src/voxgate/graph/context.py`
- Modify: `src/voxgate/graph/build.py`
- Test: `tests/test_graph_context.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RunContext(tenant_id: str, pack_id: str, actor: str, run_id: str, settings: dict | None = None)`, frozen dataclass. Graphs built by `build_graph` now accept `context=RunContext(...)` on invoke, and audit entries carry an `actor` key.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_context.py
from langgraph.checkpoint.memory import InMemorySaver
from voxgate.graph.build import build_graph
from voxgate.graph.context import RunContext
from voxgate.packs.loader import load_packs
from voxgate.config import get_settings

def _pack():
    return load_packs(get_settings().packs_dir)["kyc-uae"]

def test_audit_entries_record_the_actor():
    graph = build_graph(_pack(), InMemorySaver())
    cfg = {"configurable": {"thread_id": "t:c1"}}
    ctx = RunContext(tenant_id="t", pack_id="kyc-uae", actor="reviewer:alice", run_id="r1")

    graph.invoke({"case_id": "c1", "pack_id": "kyc-uae", "reask_count": 0},
                 cfg, context=ctx, durability="sync")

    audit = graph.get_state(cfg).values["audit"]
    assert audit, "expected at least one audit entry"
    assert all(e["actor"] == "reviewer:alice" for e in audit)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_graph_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'voxgate.graph.context'`

- [ ] **Step 3: Create `RunContext`**

```python
# src/voxgate/graph/context.py
from dataclasses import dataclass

@dataclass(frozen=True)
class RunContext:
    """Per-run identity and configuration, passed via LangGraph's `context=` kwarg.

    Deliberately NOT carried in config["configurable"] — that lands in every
    checkpoint's metadata, and config_schema is deprecated for removal in v2.0.0.
    """
    tenant_id: str
    pack_id: str
    actor: str                       # 'bot' | 'reviewer:<user_id>' | 'system'
    run_id: str
    settings: dict | None = None
```

- [ ] **Step 4: Thread the runtime through `build.py`**

In `src/voxgate/graph/build.py`, import the runtime types and declare the context schema:

```python
from langgraph.runtime import Runtime
from .context import RunContext
```

Change `build_graph`'s graph construction from `StateGraph(CaseState)` to:

```python
g = StateGraph(CaseState, context_schema=RunContext)
```

Change `_audited` so the wrapper accepts and records the runtime. The wrapped node functions keep their existing single-argument signature — only the wrapper's signature widens, so no node body changes:

```python
def _audited(name, fn, clock=None):
    def wrapper(state, runtime: Runtime[RunContext] = None):
        t0 = time.perf_counter()
        result = fn(state) or {}
        entry = {
            "seq": len(state.get("audit", [])) + 1,
            "node": name,
            "actor": getattr(getattr(runtime, "context", None), "actor", "system"),
            "status_before": state.get("status"),
            "status_after": result.get("status", state.get("status")),
            "summary": _summarize(name, state, result),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        if clock is not None:
            entry["ts"] = clock()
        return {**result, "audit": [entry]}
    return wrapper
```

The `getattr` chain defaults to `"system"` so a graph invoked with no context — which every existing test does — still works.

- [ ] **Step 5: Run the new test**

Run: `uv run pytest tests/test_graph_context.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `uv run pytest -q`
Expected: `55 passed, 1 skipped`

- [ ] **Step 7: Commit**

```bash
git add src/voxgate/graph/context.py src/voxgate/graph/build.py tests/test_graph_context.py
git commit -m "feat(graph): add RunContext for tenant and actor attribution

Audit entries now record WHO acted, not just the pack's gate_role."
```

---

## Task 3: CaseStore Protocol and in-memory implementation

**Files:**
- Rewrite: `src/voxgate/service/store.py`
- Create: `tests/contracts/__init__.py` (empty), `tests/contracts/test_case_store.py`
- Modify: `tests/test_runner.py`, `tests/test_api.py` (constructor + await)

**Interfaces:**
- Consumes: nothing.
- Produces:

```python
class CaseStore(Protocol):
    async def upsert(self, tenant_id: str, case: dict) -> dict: ...
    async def get(self, tenant_id: str, case_id: str) -> dict | None: ...
    async def list(self, tenant_id: str, pack_id: str | None = None) -> list[dict]: ...
```

`InMemoryCaseStore()` takes no arguments. All methods return **copies**, never internal references.

- [ ] **Step 1: Write the contract test suite**

```python
# tests/contracts/test_case_store.py
import os
import pytest
from voxgate.service.store import InMemoryCaseStore

async def _make_memory():
    return InMemoryCaseStore()

STORE_FACTORIES = {"memory": _make_memory}

@pytest.fixture(params=list(STORE_FACTORIES))
async def store(request):
    return await STORE_FACTORIES[request.param]()

async def test_upsert_then_get_roundtrips(store):
    await store.upsert("t1", {"case_id": "c1", "pack_id": "kyc-uae", "status": "processing"})
    got = await store.get("t1", "c1")
    assert got["case_id"] == "c1"
    assert got["status"] == "processing"

async def test_get_returns_none_for_unknown_case(store):
    assert await store.get("t1", "nope") is None

async def test_upsert_merges_rather_than_replaces(store):
    await store.upsert("t1", {"case_id": "c1", "pack_id": "kyc-uae", "status": "processing"})
    await store.upsert("t1", {"case_id": "c1", "status": "approved"})
    got = await store.get("t1", "c1")
    assert got["status"] == "approved"
    assert got["pack_id"] == "kyc-uae", "unspecified keys must survive a partial upsert"

async def test_tenants_are_isolated(store):
    await store.upsert("t1", {"case_id": "c1", "pack_id": "kyc-uae", "status": "processing"})
    assert await store.get("t2", "c1") is None
    assert await store.list("t2") == []

async def test_list_filters_by_pack(store):
    await store.upsert("t1", {"case_id": "c1", "pack_id": "kyc-uae", "status": "processing"})
    await store.upsert("t1", {"case_id": "c2", "pack_id": "other", "status": "processing"})
    assert [c["case_id"] for c in await store.list("t1", pack_id="other")] == ["c2"]

async def test_list_is_newest_first(store):
    await store.upsert("t1", {"case_id": "c1", "pack_id": "kyc-uae", "status": "processing"})
    await store.upsert("t1", {"case_id": "c2", "pack_id": "kyc-uae", "status": "processing"})
    assert [c["case_id"] for c in await store.list("t1")] == ["c2", "c1"]

async def test_mutating_a_returned_case_does_not_corrupt_the_store(store):
    """Regression: the original CaseStore handed out live internal references."""
    await store.upsert("t1", {"case_id": "c1", "pack_id": "kyc-uae", "status": "processing"})
    got = await store.get("t1", "c1")
    got["status"] = "TAMPERED"
    assert (await store.get("t1", "c1"))["status"] == "processing"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/contracts/test_case_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'InMemoryCaseStore'`

- [ ] **Step 3: Rewrite `store.py`**

```python
# src/voxgate/service/store.py
import asyncio
import copy
from typing import Protocol, runtime_checkable

@runtime_checkable
class CaseStore(Protocol):
    """Index of cases. A PROJECTION of graph state, never a source of truth.

    `_sync()` rewrites rows from `graph.get_state()`; the checkpointer owns truth.
    """
    async def upsert(self, tenant_id: str, case: dict) -> dict: ...
    async def get(self, tenant_id: str, case_id: str) -> dict | None: ...
    async def list(self, tenant_id: str, pack_id: str | None = None) -> list[dict]: ...


class InMemoryCaseStore:
    """Dev/test implementation. Behaviour is pinned by tests/contracts/test_case_store.py."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._cases: dict[tuple[str, str], dict] = {}
        self._seq = 0

    async def upsert(self, tenant_id: str, case: dict) -> dict:
        key = (tenant_id, case["case_id"])
        async with self._lock:
            existing = self._cases.get(key)
            if existing:
                merged = {**existing, **case}
            else:
                self._seq += 1
                merged = {**case, "seq": self._seq}
            merged["tenant_id"] = tenant_id
            self._cases[key] = merged
            return copy.deepcopy(merged)

    async def get(self, tenant_id: str, case_id: str) -> dict | None:
        async with self._lock:
            found = self._cases.get((tenant_id, case_id))
            return copy.deepcopy(found) if found is not None else None

    async def list(self, tenant_id: str, pack_id: str | None = None) -> list[dict]:
        async with self._lock:
            rows = [c for (t, _), c in self._cases.items()
                    if t == tenant_id and (pack_id is None or c.get("pack_id") == pack_id)]
            return [copy.deepcopy(c) for c in sorted(rows, key=lambda c: c["seq"], reverse=True)]
```

- [ ] **Step 4: Run the contract suite**

Run: `uv run pytest tests/contracts/test_case_store.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/voxgate/service/store.py tests/contracts
git commit -m "feat(store): CaseStore Protocol + tenant-aware InMemoryCaseStore

Returns copies, fixing the deferred Task-7 finding where callers received
live internal dict references."
```

---

## Task 4: Postgres store and connection pool

**Files:**
- Create: `src/voxgate/service/db.py`
- Modify: `src/voxgate/service/store.py` (add `PgCaseStore`)
- Modify: `tests/contracts/test_case_store.py` (register the postgres factory)

**Interfaces:**
- Consumes: `CaseStore` Protocol from Task 3.
- Produces: `open_pool(dsn) -> AsyncConnectionPool`, `ensure_schema(pool) -> None`, `PgCaseStore(pool)` satisfying `CaseStore`.

- [ ] **Step 1: Create `db.py`**

```python
# src/voxgate/service/db.py
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  tenant_id   text NOT NULL,
  case_id     text NOT NULL,
  pack_id     text NOT NULL,
  thread_id   text NOT NULL,
  status      text NOT NULL,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  seq         bigserial,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, case_id)
);
CREATE INDEX IF NOT EXISTS cases_queue_idx ON cases (tenant_id, status, seq DESC);
CREATE INDEX IF NOT EXISTS cases_pack_idx  ON cases (tenant_id, pack_id, seq DESC);

CREATE TABLE IF NOT EXISTS events (
  seq        bigserial PRIMARY KEY,
  tenant_id  text  NOT NULL,
  case_id    text  NOT NULL,
  kind       text  NOT NULL,
  payload    jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_case_idx ON events (tenant_id, case_id, seq);

CREATE TABLE IF NOT EXISTS runs (
  run_id     text PRIMARY KEY,
  tenant_id  text NOT NULL,
  case_id    text NOT NULL,
  pack_id    text NOT NULL,
  status     text NOT NULL,
  error      text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS runs_case_idx  ON runs (tenant_id, case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS runs_alive_idx ON runs (status) WHERE status IN ('pending','running');
"""

async def open_pool(dsn: str) -> AsyncConnectionPool:
    """autocommit and prepare_threshold=0 are REQUIRED — they are what
    AsyncPostgresSaver.from_conn_string sets, and pgbouncer breaks without them."""
    pool = AsyncConnectionPool(
        dsn, min_size=2, max_size=20, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    return pool

async def ensure_schema(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute(SCHEMA)

async def make_checkpointer(pool: AsyncConnectionPool):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    saver = AsyncPostgresSaver(pool)
    await saver.setup()          # must be called explicitly on first use
    return saver
```

- [ ] **Step 2: Add `PgCaseStore` to `store.py`**

The volatile case fields (`fields`, `score`, `check_results`, `audit`, `interrupt`, `live_fields`, `error`) live in one `payload` jsonb column; the queryable ones are real columns. This keeps the projection shape identical to the in-memory store while still allowing `WHERE status = ...` and `ORDER BY seq`.

```python
class PgCaseStore:
    def __init__(self, pool):
        self._pool = pool

    _COLS = ("case_id", "pack_id", "thread_id", "status")

    @staticmethod
    def _row_to_case(row: dict) -> dict:
        case = dict(row["payload"])
        case.update({k: row[k] for k in ("tenant_id", "case_id", "pack_id", "status", "seq")})
        return case

    async def upsert(self, tenant_id: str, case: dict) -> dict:
        existing = await self.get(tenant_id, case["case_id"])
        merged = {**(existing or {}), **case}
        payload = {k: v for k, v in merged.items()
                   if k not in ("tenant_id", "case_id", "pack_id", "status", "seq", "thread_id")}
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                """
                INSERT INTO cases (tenant_id, case_id, pack_id, thread_id, status, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, case_id) DO UPDATE
                  SET pack_id = EXCLUDED.pack_id,
                      status  = EXCLUDED.status,
                      payload = EXCLUDED.payload,
                      updated_at = now()
                RETURNING *
                """,
                (tenant_id, merged["case_id"], merged.get("pack_id", ""),
                 f"{tenant_id}:{merged['case_id']}", merged.get("status", "processing"),
                 __import__("json").dumps(payload)),
            )).fetchone()
        return self._row_to_case(row)

    async def get(self, tenant_id: str, case_id: str) -> dict | None:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT * FROM cases WHERE tenant_id = %s AND case_id = %s",
                (tenant_id, case_id))).fetchone()
        return self._row_to_case(row) if row else None

    async def list(self, tenant_id: str, pack_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM cases WHERE tenant_id = %s"
        args: list = [tenant_id]
        if pack_id is not None:
            sql += " AND pack_id = %s"
            args.append(pack_id)
        sql += " ORDER BY seq DESC"
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(sql, tuple(args))).fetchall()
        return [self._row_to_case(r) for r in rows]
```

- [ ] **Step 3: Register the Postgres factory in the contract suite**

Replace the `STORE_FACTORIES` block in `tests/contracts/test_case_store.py`:

```python
import os, uuid
import pytest
from voxgate.service.store import InMemoryCaseStore, PgCaseStore
from voxgate.service.db import open_pool, ensure_schema

TEST_DB = os.environ.get("VOXGATE_TEST_DB")

@pytest.fixture(params=["memory", "postgres"])
async def store(request):
    if request.param == "memory":
        yield InMemoryCaseStore()
        return
    if not TEST_DB:
        pytest.skip("VOXGATE_TEST_DB not set")
    pool = await open_pool(TEST_DB)
    await ensure_schema(pool)
    yield PgCaseStore(pool)
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM cases")
    await pool.close()
```

Every test then takes a unique tenant so runs do not collide. Add at the top of each test body that writes data, replacing the literal `"t1"`/`"t2"` with values derived from a fixture:

```python
@pytest.fixture
def t1():
    return f"t1-{uuid.uuid4().hex[:8]}"

@pytest.fixture
def t2():
    return f"t2-{uuid.uuid4().hex[:8]}"
```

and change each test signature to accept `t1` (and `t2` where used) instead of using the literals.

- [ ] **Step 4: Verify both paths**

Run: `uv run pytest tests/contracts/test_case_store.py -v`
Expected: 7 passed, 7 skipped (no `VOXGATE_TEST_DB`)

Then with Postgres:

```bash
docker compose up -d
VOXGATE_TEST_DB=postgresql://voxgate:voxgate@localhost:5433/voxgate uv run pytest tests/contracts/test_case_store.py -v
```

Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/voxgate/service/db.py src/voxgate/service/store.py tests/contracts/test_case_store.py
git commit -m "feat(store): PgCaseStore + async pool; contract suite runs against both impls"
```

---

## Task 5: EventBus Protocol and in-memory implementation

**Files:**
- Rewrite: `src/voxgate/service/events.py`
- Create: `tests/contracts/test_event_bus.py`

**Interfaces:**
- Consumes: nothing.
- Produces:

```python
class EventBus(Protocol):
    async def publish(self, tenant_id: str, case_id: str, kind: str, payload: dict) -> int: ...
    async def replay(self, tenant_id: str, case_id: str, after_seq: int = 0) -> list[dict]: ...
    def subscribe(self, tenant_id: str, case_id: str) -> AsyncIterator[dict]: ...
```

`publish` returns the assigned `seq`. Every yielded/returned event is a dict with keys `seq`, `kind`, `payload`.

- [ ] **Step 1: Write the contract test suite**

```python
# tests/contracts/test_event_bus.py
import asyncio, uuid
import pytest
from voxgate.service.events import InMemoryEventBus

@pytest.fixture
def tid():
    return f"t-{uuid.uuid4().hex[:8]}"

@pytest.fixture(params=["memory"])
async def bus(request):
    yield InMemoryEventBus()

async def test_publish_returns_monotonic_seq(bus, tid):
    a = await bus.publish(tid, "c1", "state", {"status": "processing"})
    b = await bus.publish(tid, "c1", "state", {"status": "approved"})
    assert b > a

async def test_replay_returns_everything_after_a_seq(bus, tid):
    s1 = await bus.publish(tid, "c1", "state", {"n": 1})
    await bus.publish(tid, "c1", "state", {"n": 2})
    got = await bus.replay(tid, "c1", after_seq=s1)
    assert [e["payload"]["n"] for e in got] == [2]

async def test_replay_from_zero_returns_all(bus, tid):
    await bus.publish(tid, "c1", "state", {"n": 1})
    await bus.publish(tid, "c1", "state", {"n": 2})
    assert len(await bus.replay(tid, "c1", after_seq=0)) == 2

async def test_replay_is_scoped_to_the_case(bus, tid):
    await bus.publish(tid, "c1", "state", {"n": 1})
    await bus.publish(tid, "c2", "state", {"n": 99})
    got = await bus.replay(tid, "c1", after_seq=0)
    assert [e["payload"]["n"] for e in got] == [1]

async def test_subscriber_receives_events_published_after_subscribing(bus, tid):
    received = []

    async def consume():
        async for evt in bus.subscribe(tid, "c1"):
            received.append(evt)
            if len(received) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await bus.publish(tid, "c1", "state", {"n": 1})
    await bus.publish(tid, "c1", "state", {"n": 2})
    await asyncio.wait_for(task, timeout=3)
    assert [e["payload"]["n"] for e in received] == [1, 2]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/contracts/test_event_bus.py -v`
Expected: FAIL — `ImportError: cannot import name 'InMemoryEventBus'`

- [ ] **Step 3: Rewrite `events.py`**

```python
# src/voxgate/service/events.py
import asyncio
from typing import AsyncIterator, Protocol, runtime_checkable

@runtime_checkable
class EventBus(Protocol):
    async def publish(self, tenant_id: str, case_id: str, kind: str, payload: dict) -> int: ...
    async def replay(self, tenant_id: str, case_id: str, after_seq: int = 0) -> list[dict]: ...
    def subscribe(self, tenant_id: str, case_id: str) -> AsyncIterator[dict]: ...


class InMemoryEventBus:
    """Dev/test implementation. Behaviour pinned by tests/contracts/test_event_bus.py."""

    def __init__(self):
        self._seq = 0
        self._log: dict[tuple[str, str], list[dict]] = {}
        self._subs: dict[tuple[str, str], set[asyncio.Queue]] = {}

    async def publish(self, tenant_id: str, case_id: str, kind: str, payload: dict) -> int:
        key = (tenant_id, case_id)
        self._seq += 1
        event = {"seq": self._seq, "kind": kind, "payload": payload}
        self._log.setdefault(key, []).append(event)
        for q in self._subs.get(key, ()):
            q.put_nowait(event)
        return self._seq

    async def replay(self, tenant_id: str, case_id: str, after_seq: int = 0) -> list[dict]:
        return [e for e in self._log.get((tenant_id, case_id), []) if e["seq"] > after_seq]

    async def subscribe(self, tenant_id: str, case_id: str) -> AsyncIterator[dict]:
        key = (tenant_id, case_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs.setdefault(key, set()).add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs[key].discard(q)
```

- [ ] **Step 4: Run the contract suite**

Run: `uv run pytest tests/contracts/test_event_bus.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/voxgate/service/events.py tests/contracts/test_event_bus.py
git commit -m "feat(events): EventBus Protocol + InMemoryEventBus with seq replay"
```

---

## Task 6: Postgres event bus with LISTEN/NOTIFY

**Files:**
- Modify: `src/voxgate/service/events.py` (add `PgEventBus`)
- Modify: `tests/contracts/test_event_bus.py` (register the postgres factory)

**Interfaces:**
- Consumes: `EventBus` Protocol (Task 5), `open_pool`/`ensure_schema` (Task 4).
- Produces: `PgEventBus(pool, dsn)` satisfying `EventBus`, plus `await bus.start()` / `await bus.stop()` for the listener task.

- [ ] **Step 1: Write the payload-size test**

```python
# append to tests/contracts/test_event_bus.py
import json

def test_notify_payload_stays_under_the_postgres_limit():
    """pg_notify caps payloads at 8000 bytes. We notify with identifiers only
    and let the SSE handler read the row, so this must hold for any case."""
    from voxgate.service.events import PgEventBus
    notify = PgEventBus._notify_payload("tenant-with-a-fairly-long-name",
                                        "8f14e45f-ceea-467a-9f7c-1a2b3c4d5e6f",
                                        "state", 999999999)
    assert len(json.dumps(notify).encode()) < 7900
    assert set(notify) == {"tenant_id", "case_id", "kind", "seq"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/contracts/test_event_bus.py -k notify_payload -v`
Expected: FAIL — `ImportError: cannot import name 'PgEventBus'`

- [ ] **Step 3: Implement `PgEventBus`**

```python
import json
import psycopg

class PgEventBus:
    """One dedicated LISTEN connection per worker process, fanned out in-process.

    NEVER one connection per browser client. Notification payloads carry
    identifiers only (pg_notify caps at 8000 bytes); subscribers read the row.
    """

    CHANNEL = "voxgate_events"

    def __init__(self, pool, dsn: str):
        self._pool, self._dsn = pool, dsn
        self._subs: dict[tuple[str, str], set[asyncio.Queue]] = {}
        self._listener: asyncio.Task | None = None
        self._conn = None

    @staticmethod
    def _notify_payload(tenant_id: str, case_id: str, kind: str, seq: int) -> dict:
        return {"tenant_id": tenant_id, "case_id": case_id, "kind": kind, "seq": seq}

    async def publish(self, tenant_id: str, case_id: str, kind: str, payload: dict) -> int:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO events (tenant_id, case_id, kind, payload) "
                "VALUES (%s, %s, %s, %s) RETURNING seq",
                (tenant_id, case_id, kind, json.dumps(payload)))).fetchone()
            seq = row["seq"]
            await conn.execute(
                "SELECT pg_notify(%s, %s)",
                (self.CHANNEL,
                 json.dumps(self._notify_payload(tenant_id, case_id, kind, seq))))
        return seq

    async def replay(self, tenant_id: str, case_id: str, after_seq: int = 0) -> list[dict]:
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT seq, kind, payload FROM events "
                "WHERE tenant_id = %s AND case_id = %s AND seq > %s ORDER BY seq",
                (tenant_id, case_id, after_seq))).fetchall()
        return [{"seq": r["seq"], "kind": r["kind"], "payload": r["payload"]} for r in rows]

    async def start(self) -> None:
        self._conn = await psycopg.AsyncConnection.connect(self._dsn, autocommit=True)
        await self._conn.execute(f"LISTEN {self.CHANNEL}")
        self._listener = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async for note in self._conn.notifies():
            data = json.loads(note.payload)
            key = (data["tenant_id"], data["case_id"])
            subs = self._subs.get(key)
            if not subs:
                continue
            rows = await self.replay(*key, after_seq=data["seq"] - 1)
            for event in rows:
                if event["seq"] != data["seq"]:
                    continue
                for q in subs:
                    q.put_nowait(event)

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
        if self._conn:
            await self._conn.close()

    async def subscribe(self, tenant_id: str, case_id: str) -> AsyncIterator[dict]:
        key = (tenant_id, case_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs.setdefault(key, set()).add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs[key].discard(q)
```

- [ ] **Step 4: Register the postgres factory**

Replace the `bus` fixture in `tests/contracts/test_event_bus.py`:

```python
import os
from voxgate.service.events import InMemoryEventBus, PgEventBus
from voxgate.service.db import open_pool, ensure_schema

TEST_DB = os.environ.get("VOXGATE_TEST_DB")

@pytest.fixture(params=["memory", "postgres"])
async def bus(request):
    if request.param == "memory":
        yield InMemoryEventBus()
        return
    if not TEST_DB:
        pytest.skip("VOXGATE_TEST_DB not set")
    pool = await open_pool(TEST_DB)
    await ensure_schema(pool)
    b = PgEventBus(pool, TEST_DB)
    await b.start()
    yield b
    await b.stop()
    await pool.close()
```

- [ ] **Step 5: Verify both paths**

Run: `uv run pytest tests/contracts/test_event_bus.py -v`
Expected: 6 passed, 5 skipped

With Postgres running:

```bash
VOXGATE_TEST_DB=postgresql://voxgate:voxgate@localhost:5433/voxgate uv run pytest tests/contracts/test_event_bus.py -v
```

Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add src/voxgate/service/events.py tests/contracts/test_event_bus.py
git commit -m "feat(events): PgEventBus via LISTEN/NOTIFY with identifier-only payloads"
```

---

## Task 7: Async CaseRunner

**Files:**
- Rewrite: `src/voxgate/service/runner.py`
- Modify: `tests/test_runner.py`

**Interfaces:**
- Consumes: `CaseStore`, `EventBus`, `RunContext`.
- Produces:

```python
class CaseRunner:
    def __init__(self, packs, checkpointer, store: CaseStore, bus: EventBus)
    async def start_case(self, tenant_id, pack_id, *, actor="system", run_id="") -> dict
    async def resume(self, tenant_id, case_id, payload, *, actor="system", run_id="") -> dict
    async def continue_case(self, tenant_id, case_id, *, actor="system", run_id="") -> dict
    async def patch_fields(self, tenant_id, case_id, fields, confidence) -> dict
    async def sync(self, tenant_id, case_id, pack_id) -> dict
```

`recover_case` is **deleted** — the Postgres index makes it unnecessary. `continue_case` resumes a thread from its checkpoint with a `None` input; it is NOT `Command(resume=None)`.

> **Before you start.** This task rewrites `runner.py`. Two things in the
> current file must survive the rewrite:
>
> | Must survive | Why |
> |---|---|
> | `self.checkpointer` set in `__init__` | `packs/publish.py:register()` compiles a newly published pack onto it. Drop the attribute and `POST /packs/publish` raises `AttributeError`. Covered by `tests/test_publish.py::test_published_pack_runs_a_real_case`. |
> | `patch_fields` behaviour | The applicant interview PATCHes live fields during a call. |
>
> `recover_case` is the one method this task deliberately DELETES: the Postgres
> case index from Task 3 makes it unnecessary.
>
> If `tests/test_publish.py` fails after your rewrite, you dropped the
> checkpointer. Restore it.

- [ ] **Step 1: Rewrite `runner.py`**

Note the constructor change: it now takes an already-built `checkpointer` rather than a factory, because the pool is created in the FastAPI lifespan.

```python
# src/voxgate/service/runner.py
import uuid
from langgraph.types import Command
from voxgate.graph.context import RunContext


class CaseRunner:
    def __init__(self, packs, checkpointer, store, bus):
        self.packs, self.store, self.bus = packs, store, bus
        from voxgate.graph.build import build_graph
        self.graphs = {pid: build_graph(p, checkpointer) for pid, p in packs.items()}

    @staticmethod
    def thread_id(tenant_id: str, case_id: str) -> str:
        return f"{tenant_id}:{case_id}"

    def _cfg(self, tenant_id, case_id):
        return {"configurable": {"thread_id": self.thread_id(tenant_id, case_id)}}

    def _ctx(self, tenant_id, pack_id, actor, run_id):
        return RunContext(tenant_id=tenant_id, pack_id=pack_id, actor=actor, run_id=run_id)

    async def sync(self, tenant_id, case_id, pack_id) -> dict:
        graph = self.graphs[pack_id]
        snap = await graph.aget_state(self._cfg(tenant_id, case_id))
        values = snap.values
        pending = None
        for task in snap.tasks:
            if task.interrupts:
                pending = task.interrupts[0].value
        case = {
            "case_id": case_id, "pack_id": pack_id,
            "status": values.get("status", "processing"),
            "fields": values.get("fields", {}),
            "score": values.get("score"), "decision": values.get("decision"),
            "check_results": values.get("check_results", []),
            "audit": values.get("audit", []),
            "interrupt": pending,
        }
        stored = await self.store.upsert(tenant_id, case)
        await self.bus.publish(tenant_id, case_id, "state", stored)
        return stored

    async def _fail(self, tenant_id, case_id, pack_id, exc) -> dict:
        stored = await self.store.upsert(tenant_id, {
            "case_id": case_id, "pack_id": pack_id,
            "status": "needs_attention", "error": str(exc)})
        await self.bus.publish(tenant_id, case_id, "state", stored)
        return stored

    async def _drive(self, tenant_id, case_id, pack_id, graph_input, actor, run_id) -> dict:
        try:
            await self.graphs[pack_id].ainvoke(
                graph_input, self._cfg(tenant_id, case_id),
                context=self._ctx(tenant_id, pack_id, actor, run_id),
                durability="sync")
        except Exception as exc:
            return await self._fail(tenant_id, case_id, pack_id, exc)
        return await self.sync(tenant_id, case_id, pack_id)

    async def start_case(self, tenant_id, pack_id, *, actor="system", run_id="") -> dict:
        case_id = str(uuid.uuid4())
        await self.store.upsert(tenant_id, {
            "case_id": case_id, "pack_id": pack_id,
            "status": "awaiting_interview", "live_fields": {}})
        return await self._drive(
            tenant_id, case_id, pack_id,
            {"case_id": case_id, "pack_id": pack_id, "reask_count": 0}, actor, run_id)

    async def _pack_of(self, tenant_id, case_id) -> str:
        case = await self.store.get(tenant_id, case_id)
        if case is None:
            raise KeyError(case_id)
        return case["pack_id"]

    async def resume(self, tenant_id, case_id, payload, *, actor="system", run_id="") -> dict:
        pack_id = await self._pack_of(tenant_id, case_id)
        return await self._drive(tenant_id, case_id, pack_id,
                                 Command(resume=payload), actor, run_id)

    async def continue_case(self, tenant_id, case_id, *, actor="system", run_id="") -> dict:
        """Resume a thread from its checkpoint after a crash.

        `None` input means 'continue this thread'. This is NOT Command(resume=None),
        which would answer a pending interrupt with a None payload and crash the node.
        """
        pack_id = await self._pack_of(tenant_id, case_id)
        return await self._drive(tenant_id, case_id, pack_id, None, actor, run_id)

    async def patch_fields(self, tenant_id, case_id, fields, confidence) -> dict:
        case = await self.store.get(tenant_id, case_id)
        if case is None:
            raise KeyError(case_id)
        live = {**case.get("live_fields", {}), **fields}
        stored = await self.store.upsert(tenant_id, {
            "case_id": case_id, "pack_id": case["pack_id"], "live_fields": live})
        await self.bus.publish(tenant_id, case_id, "fields",
                               {"fields": live, "confidence": confidence})
        return stored
```

- [ ] **Step 2: Update `tests/test_runner.py`**

Every construction becomes `CaseRunner(packs, InMemorySaver(), InMemoryCaseStore(), InMemoryEventBus())`, every call gains a `tenant_id` first argument and an `await`. Example conversion:

```python
async def test_start_case_parks_at_the_interview_interrupt(packs):
    runner = CaseRunner(packs, InMemorySaver(), InMemoryCaseStore(), InMemoryEventBus())
    case = await runner.start_case("t1", "kyc-uae")
    assert case["status"] == "awaiting_interview"
    assert case["interrupt"]["type"] == "interview"
```

- [ ] **Step 3: Run the runner tests**

Run: `uv run pytest tests/test_runner.py -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/voxgate/service/runner.py tests/test_runner.py
git commit -m "feat(runner): async CaseRunner, tenant-aware, durability=sync

Deletes recover_case — the Postgres case index makes it unnecessary.
Adds continue_case for crash recovery (None input, NOT Command(resume=None))."
```

---

## Task 8: RunWorker

**Files:**
- Create: `src/voxgate/service/runs.py`
- Create: `tests/test_runs.py`

**Interfaces:**
- Consumes: `CaseRunner` (Task 7), `CaseStore`, `EventBus`.
- Produces:

```python
class RunInProgress(Exception): ...

class InMemoryRunStore:
    async def create(self, run_id, tenant_id, case_id, pack_id) -> None
    async def set_status(self, run_id, status, error=None) -> None
    async def get(self, run_id) -> dict | None
    async def alive(self) -> list[dict]

class RunWorker:
    def __init__(self, runner, runs, concurrency: int = 10)
    async def submit(self, tenant_id, case_id, pack_id, *, kind, payload=None,
                     actor="system", multitask="reject") -> str
    async def wait(self, run_id: str, timeout: float = 30.0) -> dict | None
    async def recover_orphans(self) -> int
    async def shutdown(self) -> None
```

`kind` is one of `"start"`, `"resume"`, `"continue"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_runs.py
import asyncio
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.events import InMemoryEventBus
from voxgate.service.runner import CaseRunner
from voxgate.service.runs import InMemoryRunStore, RunInProgress, RunWorker
from voxgate.service.store import InMemoryCaseStore

@pytest.fixture
def worker():
    packs = load_packs(get_settings().packs_dir)
    runner = CaseRunner(packs, InMemorySaver(), InMemoryCaseStore(), InMemoryEventBus())
    return RunWorker(runner, InMemoryRunStore())

async def test_submit_returns_a_run_id_and_completes(worker):
    run_id = await worker.submit("t1", None, "kyc-uae", kind="start")
    result = await worker.wait(run_id, timeout=10)
    assert result["status"] == "awaiting_interview"
    assert (await worker.runs.get(run_id))["status"] == "succeeded"

async def test_second_concurrent_run_on_one_case_is_rejected(worker):
    run_id = await worker.submit("t1", None, "kyc-uae", kind="start")
    case = await worker.wait(run_id, timeout=10)
    cid = case["case_id"]

    worker._gate.set()                       # hold the next run open
    await worker.submit("t1", cid, "kyc-uae", kind="resume",
                        payload={"fields": {"full_name": "A"}, "confidence": {}})
    with pytest.raises(RunInProgress):
        await worker.submit("t1", cid, "kyc-uae", kind="resume",
                            payload={"fields": {}, "confidence": {}})
    worker._gate.clear()

async def test_wait_times_out_without_killing_the_run(worker):
    run_id = await worker.submit("t1", None, "kyc-uae", kind="start")
    assert await worker.wait(run_id, timeout=0.0) is None      # too impatient
    assert await worker.wait(run_id, timeout=10) is not None    # still finished

async def test_orphan_parked_at_an_interrupt_is_marked_succeeded_not_reexecuted(worker):
    """A run row left 'running' whose graph is parked at an interrupt did in fact
    finish — only the status write was lost. Re-submitting would answer the
    interrupt with a None payload and crash the node."""
    run_id = await worker.submit("t1", None, "kyc-uae", kind="start")
    case = await worker.wait(run_id, timeout=10)
    await worker.runs.set_status(run_id, "running")            # simulate a lost write

    recovered = await worker.recover_orphans()

    assert recovered == 1
    assert (await worker.runs.get(run_id))["status"] == "succeeded"
    still = await worker.runner.store.get("t1", case["case_id"])
    assert still["status"] == "awaiting_interview", "must not have been re-executed"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'voxgate.service.runs'`

- [ ] **Step 3: Implement `runs.py`**

```python
# src/voxgate/service/runs.py
import asyncio
import uuid


class RunInProgress(Exception):
    """A run is already active for this case and multitask policy is 'reject'."""


class InMemoryRunStore:
    def __init__(self):
        self._runs: dict[str, dict] = {}

    async def create(self, run_id, tenant_id, case_id, pack_id) -> None:
        self._runs[run_id] = {"run_id": run_id, "tenant_id": tenant_id,
                              "case_id": case_id, "pack_id": pack_id,
                              "status": "pending", "error": None}

    async def set_status(self, run_id, status, error=None) -> None:
        self._runs[run_id].update(status=status, error=error)

    async def set_case_id(self, run_id, case_id) -> None:
        self._runs[run_id]["case_id"] = case_id

    async def get(self, run_id) -> dict | None:
        found = self._runs.get(run_id)
        return dict(found) if found else None

    async def alive(self) -> list[dict]:
        return [dict(r) for r in self._runs.values()
                if r["status"] in ("pending", "running")]


class RunWorker:
    """One asyncio task per run, semaphore-bounded.

    Execution leaves the request thread entirely. POST handlers call submit()
    and return 202; ?wait= awaits the completion future without forking the
    execution path.
    """

    def __init__(self, runner, runs, concurrency: int = 10):
        self.runner, self.runs = runner, runs
        self._sem = asyncio.Semaphore(concurrency)
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._gate = asyncio.Event()          # test hook: hold runs open

    async def submit(self, tenant_id, case_id, pack_id, *, kind,
                     payload=None, actor="system", multitask="reject") -> str:
        key = (tenant_id, case_id)
        if case_id is not None:
            active = self._tasks.get(key)
            if active and not active.done():
                if multitask == "reject":
                    raise RunInProgress(case_id)
                if multitask == "interrupt":
                    active.cancel()           # checkpoint survives; safe to re-enter

        run_id = str(uuid.uuid4())
        await self.runs.create(run_id, tenant_id, case_id, pack_id)
        loop = asyncio.get_running_loop()
        self._futures[run_id] = loop.create_future()
        task = asyncio.create_task(
            self._execute(run_id, tenant_id, case_id, pack_id, kind, payload, actor))
        if case_id is not None:
            self._tasks[key] = task
        return run_id

    async def _execute(self, run_id, tenant_id, case_id, pack_id, kind, payload, actor):
        fut = self._futures[run_id]
        async with self._sem:
            await self.runs.set_status(run_id, "running")
            try:
                if self._gate.is_set():
                    await self._gate.wait()
                if kind == "start":
                    case = await self.runner.start_case(
                        tenant_id, pack_id, actor=actor, run_id=run_id)
                    await self.runs.set_case_id(run_id, case["case_id"])
                    self._tasks[(tenant_id, case["case_id"])] = asyncio.current_task()
                elif kind == "resume":
                    case = await self.runner.resume(
                        tenant_id, case_id, payload, actor=actor, run_id=run_id)
                else:
                    case = await self.runner.continue_case(
                        tenant_id, case_id, actor=actor, run_id=run_id)
                await self.runs.set_status(run_id, "succeeded")
                if not fut.done():
                    fut.set_result(case)
                return case
            except asyncio.CancelledError:
                await self.runs.set_status(run_id, "cancelled")
                if not fut.done():
                    fut.cancel()
                raise
            except Exception as exc:
                await self.runs.set_status(run_id, "failed", str(exc))
                if not fut.done():
                    fut.set_exception(exc)
                raise

    async def wait(self, run_id: str, timeout: float = 30.0) -> dict | None:
        """Await the run's result. On timeout returns None — the run continues.
        This is a convenience, never a correctness guarantee."""
        fut = self._futures.get(run_id)
        if fut is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return None

    async def recover_orphans(self) -> int:
        """Reconcile runs left 'running'/'pending' against the checkpointer.

        A stalled row has two causes and they need opposite treatment:
          - graph parked at an interrupt -> the run finished; only the status
            write was lost. Mark succeeded. Do NOT re-execute.
          - killed mid-execution -> continue from the checkpoint.
        """
        recovered = 0
        for run in await self.runs.alive():
            case_id, tenant_id = run["case_id"], run["tenant_id"]
            if case_id is None:
                await self.runs.set_status(run["run_id"], "failed", "orphaned before start")
                recovered += 1
                continue
            graph = self.runner.graphs[run["pack_id"]]
            snap = await graph.aget_state(self.runner._cfg(tenant_id, case_id))
            if any(t.interrupts for t in snap.tasks):
                await self.runs.set_status(run["run_id"], "succeeded")
                await self.runner.sync(tenant_id, case_id, run["pack_id"])
            else:
                await self.runner.continue_case(tenant_id, case_id, actor="system",
                                                run_id=run["run_id"])
                await self.runs.set_status(run["run_id"], "succeeded")
            recovered += 1
        return recovered

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_runs.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/voxgate/service/runs.py tests/test_runs.py
git commit -m "feat(runs): RunWorker with multitask policy and orphan reconciliation

Orphan recovery distinguishes 'parked at an interrupt' (mark succeeded, do
not re-execute) from 'killed mid-execution' (continue from checkpoint)."
```

---

## Task 9: HTTP surface — lifespan, tenancy, 202, SSE

**Files:**
- Modify: `src/voxgate/service/app.py`
- Modify: `tests/test_api.py`
- Modify: `scripts/demo_case.py`

**Interfaces:**
- Consumes: everything from Tasks 3–8.
- Produces: `create_app(settings=None, runner=None, worker=None) -> FastAPI`; routes per the spec §4.7.

- [ ] **Step 1: Write the failing API tests**

```python
# additions to tests/test_api.py
async def test_create_case_returns_202_with_a_run_id(client):
    r = await client.post("/cases", json={"pack_id": "kyc-uae"})
    assert r.status_code == 202
    assert set(r.json()) >= {"run_id", "status"}

async def test_create_case_with_wait_returns_the_full_case(client):
    r = await client.post("/cases?wait=true", json={"pack_id": "kyc-uae"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "awaiting_interview"
    assert body["interrupt"]["type"] == "interview"

async def test_unknown_case_is_404(client):
    r = await client.get("/cases/does-not-exist")
    assert r.status_code == 404

async def test_events_endpoint_is_sse(client):
    r = await client.post("/cases?wait=true", json={"pack_id": "kyc-uae"})
    cid = r.json()["case_id"]
    async with client.stream("GET", f"/cases/{cid}/events") as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL — currently returns 201 with a full case and has no SSE route

- [ ] **Step 3: Modify `app.py` — ADDITIVELY. Do not rewrite the file.**

> **STOP.** An earlier version of this plan contained a full replacement
> `app.py`. It was written before several features landed and pasting it would
> delete working, tested code. It has been removed. Edit the existing file.
>
> **These must still exist and behave identically when you are done:**
>
> | Must survive | Why |
> |---|---|
> | `CORSMiddleware` block and `settings.cors_origins` | Without it the browser blocks every request while `curl` still works, which presents as "backend is down". |
> | `POST /packs/{pack_id}/extract` | The applicant interview calls it. Covered by `tests/test_api_ml.py`. |
> | `POST /packs/draft` | The pack-drafting backend. Same test file. |
> | `POST /packs/publish` | Writes a drafted spec to disk and compiles a live graph. Covered by `tests/test_publish.py`. |
> | `reask_hints` in the `GET /packs` response | `/apply` reads its questions from it. Asserted in `tests/test_api.py::test_packs_listing`. |
>
> If any test in `tests/test_api_ml.py` fails, you deleted something. Restore it.

Make these changes, and only these:

**3a. Lifespan.** Replace the module-level construction with a FastAPI
`lifespan` that opens the pool, runs `ensure_schema`, builds the checkpointer,
store and bus, constructs the `CaseRunner` and `RunWorker`, calls
`await worker.recover_orphans()`, and tears all of it down on shutdown. When
`settings.database_url` is unset, build the in-memory implementations instead —
the suite must still run with no Postgres.

**3b. Tenant dependency.** Add:

```python
async def current_tenant(request: Request) -> str:
    """Stub. Swap for JWT / API-key resolution; every query already scopes by it."""
    return "default"
```

and an `owned_case` dependency that fetches through the store with the tenant in
the WHERE clause and raises **404, never 403**, so there is no existence oracle.
Route every case-scoped endpoint through it.

**3c. Async + 202.** `POST /cases`, `POST /cases/{id}/interview-result` and
`POST /cases/{id}/decision` become async, submit to the `RunWorker`, and return
`202 {"run_id", "status"}`. Each accepts `?wait=true`, which awaits the run's
completion future with a 30s timeout and returns the full case on success. On
timeout return 202 with the `run_id` — the run continues; only the client's
patience expired. `RunInProgress` becomes **409**.

**3d. Add `GET /runs/{run_id}`** returning the run row.

**3e. Replace the WebSocket with SSE.** Delete the `@app.websocket` handler and
add `GET /cases/{case_id}/events` returning an `EventSourceResponse` that first
replays from `Last-Event-ID`, then streams from `bus.subscribe`. Set
`X-Accel-Buffering: no`. Each yielded event carries `id`, `event` and `data`.

**3f. Do not build `POST /cases/{id}/recover`.** The Postgres index makes it
unnecessary; delete `recover_case` from the runner instead.


- [ ] **Step 4: Convert `tests/test_api.py` to an async client**

```python
import pytest
from httpx import ASGITransport, AsyncClient
from voxgate.service.app import create_app

@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c
```

- [ ] **Step 5: Update `scripts/demo_case.py`**

Append `?wait=true` to the three POST calls so the script stays a linear read-the-response flow.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: all pass, no failures

- [ ] **Step 7: Manual smoke test**

```bash
uv run uvicorn voxgate.service.app:app --port 8000
curl -s http://127.0.0.1:8000/packs
curl -s -X POST "http://127.0.0.1:8000/cases?wait=true" -H "Content-Type: application/json" -d '{"pack_id":"kyc-uae"}'
uv run python scripts/demo_case.py --risky
```

Expected: packs list; a case parked at `awaiting_interview`; the demo runs end to end.

- [ ] **Step 8: Commit**

```bash
git add src/voxgate/service/app.py tests/test_api.py scripts/demo_case.py
git commit -m "feat(api): 202 + run_id with ?wait= escape hatch, SSE replaces WebSocket

Adds lifespan-owned pool, tenant dependency returning 404 not 403,
GET /runs/{run_id}, and Last-Event-ID replay. Removes the WS endpoint,
which burned a thread per client on a 1s poll."
```

---

## Task 10: Next.js scaffold

**Files:**
- Create: `apps/web/` (Next.js app), `apps/web/app/page.tsx`, `apps/web/app/globals.css`, `apps/web/lib/api.ts`

**Interfaces:**
- Consumes: `GET /packs` and `GET /cases` — deliberately the only two endpoints whose shape does **not** change in this plan.
- Produces: a runnable dev server proving the design tokens port cleanly.

**Scope boundary:** this is a scaffold, not the dashboard. No case detail, no drawer, no charts, no voice orb — those depend on API shapes and decisions (captions strategy) that are not settled. Building them now means building them twice.

- [ ] **Step 1: Scaffold the app**

```bash
cd C:/Users/GAURAV/OneDrive/Desktop/PPC_Tech/voxgate
npx create-next-app@latest apps/web --typescript --app --tailwind --eslint --no-src-dir --import-alias "@/*" --use-npm
```

- [ ] **Step 2: Port the design tokens**

Copy the `:root` block from `src/voxgate/service/static/dashboard.css` (lines 7–65) into `apps/web/app/globals.css` verbatim, below the Tailwind directives. These are the real values — do not invent replacements.

- [ ] **Step 3: Add the API client**

```typescript
// apps/web/lib/api.ts
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Pack = {
  pack_id: string;
  display_name: string;
  gate_role: string;
  fields: string[];
};

export async function getPacks(): Promise<Pack[]> {
  const res = await fetch(`${BASE}/packs`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET /packs failed: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 4: Render the packs**

```tsx
// apps/web/app/page.tsx
import { getPacks } from "@/lib/api";

export default async function Home() {
  let packs;
  try {
    packs = await getPacks();
  } catch {
    return (
      <main style={{ padding: 40, color: "var(--text)" }}>
        <h1>VoxGate</h1>
        <p style={{ color: "var(--status-needs_attention)" }}>
          Backend unreachable. Start it with:{" "}
          <code>uv run uvicorn voxgate.service.app:app</code>
        </p>
      </main>
    );
  }

  return (
    <main style={{ padding: 40, color: "var(--text)" }}>
      <h1 style={{ fontSize: 28, marginBottom: 24 }}>VoxGate — Compliance Packs</h1>
      {packs.map((p) => (
        <section
          key={p.pack_id}
          style={{
            background: "var(--glass)",
            border: "1px solid var(--glass-border)",
            borderRadius: "var(--r-md)",
            padding: "var(--sp-5)",
            marginBottom: "var(--sp-4)",
          }}
        >
          <h2 style={{ fontSize: 18 }}>{p.display_name}</h2>
          <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
            Gate: {p.gate_role} · {p.fields.length} fields
          </p>
        </section>
      ))}
    </main>
  );
}
```

- [ ] **Step 5: Set the dark background**

In `apps/web/app/layout.tsx`, set `<body style={{ background: "var(--bg)" }}>`.

- [ ] **Step 6: Run both and verify**

Terminal 1: `uv run uvicorn voxgate.service.app:app --port 8000`
Terminal 2: `cd apps/web && npm run dev`

Open `http://localhost:3000`. Expected: the UAE Fintech KYC Onboarding pack rendered on the dark background with the real token colours. Stop the backend and reload — expected: the "Backend unreachable" message, not a crash.

- [ ] **Step 7: Commit**

```bash
git add apps/web .gitignore
git commit -m "feat(web): Next.js scaffold rendering /packs with ported design tokens

Deliberately limited to endpoints whose shape does not change, so no UI
work is invalidated by the remaining spine tasks."
```

---

## Definition of Done

Verify each, in order:

1. `uv run pytest -q` → all pass, offline, no Docker.
2. `docker compose up -d && VOXGATE_TEST_DB=... uv run pytest -q` → contract suites pass against Postgres.
3. Restart the server with Postgres configured; `GET /cases/{id}` still returns a case created before the restart — with **no** `recover_case` call.
4. Two concurrent resumes on one case: one succeeds, one returns 409.
5. `uv run python scripts/demo_case.py --risky` runs end to end.
6. An SSE client reconnecting with `Last-Event-ID` sees no gap and no duplicate.
7. No route blocks a worker thread on graph execution.
8. `cd apps/web && npm run dev` renders the packs page against the live API.

---

## Self-Review Notes

**Spec coverage:** §4.1 → Task 4. §4.2 → Task 2. §4.3 (frozen topology) → honoured throughout; no task touches routing functions. §4.4 → Tasks 3–4. §4.5 → Tasks 5–6. §4.6 → Task 8. §4.7 → Task 9. §6.1 contract suites → Tasks 3, 5. §6.2 tests 1–3 → Task 8; test 4 (SSE replay) → Task 9 Step 1; test 5 (tenant isolation) → Task 3.

**Known gap, deliberate:** spec §6.2 test 2 (durability `exit` versus `sync` losing a checkpoint) is **not** implemented as a task. It requires killing a process mid-superstep, which is awkward to make deterministic and is not on the critical path. Recorded here rather than silently dropped — add it during the Postgres integration pass if the demo needs it.

**Type consistency:** `CaseStore.get(tenant_id, case_id)` and `EventBus.publish(tenant_id, case_id, kind, payload) -> int` are used identically in Tasks 3–9. `RunWorker.submit(...)` keyword `kind` matches its three call sites in Task 9. `continue_case` is named consistently in Tasks 7 and 8.
