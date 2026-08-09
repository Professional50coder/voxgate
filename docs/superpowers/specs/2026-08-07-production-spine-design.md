# VoxGate Production Spine — Design

**Date:** 2026-08-07
**Status:** Approved for implementation planning
**Scope:** Sub-project 1 of 4. The backend production spine only.

**Research backing:** `docs/research/2026-08-07-langgraph-production-upgrade.md`. Every
LangGraph API claim in this spec was verified against the installed 1.2.10 source, not
documentation — in three places the source contradicts the docs, and those are called out
inline.

---

## 1. Why this exists

VoxGate's backend is complete and green (54 passed, 1 skipped) but it is a **demo spine**, not
a production one. Three specific properties make it so:

1. **`CaseRunner` calls `.invoke()` synchronously inside a FastAPI request thread.** The
   project's own parked finding in `.paul/STATE.md` admits this is safe only because "no
   LLM/network-calling nodes exist yet."
2. **`CaseStore` is an in-memory dict.** It dies on restart and does not work across
   processes. After a restart, `GET /cases/{id}` returns 404 even though the Postgres
   checkpoint survived — this is remaining-item #3 in `.paul/STATE.md`.
3. **`EventBus` is an in-memory dict**, with a WebSocket handler that burns a thread per
   connected client on a 1-second poll (`asyncio.to_thread(bus.wait, ...)`).

Property 1 is the urgent one. **It expires the moment the voice layer or Groq integration
lands**, because those are precisely the latency-bearing nodes it assumes away. Both are next
on the roadmap. Building either on top of the current spine means building it twice.

This sub-project was chosen first for exactly that reason: it is the prerequisite that stops
the other three from being built twice.

### Explicit non-goals

- Voice, frontend, and Groq integration. Separate sub-projects, each with its own spec.
- Real authentication. The tenancy *seam* is built; the identity provider is not chosen.
- Interview subgraph extraction and the `Command` refactor. Deferred to the voice
  sub-project, which is where they pay off (see §4.3).
- Redis, distributed task brokers, node caching, `Store` API, `Send` fan-out. All deferrable
  at no cost per the research; all have identified upgrade triggers.

---

## 2. Decisions taken

Four decisions were settled before this design was written. Each is recorded with its
rationale, because each has a retrofit cost.

| # | Decision | Rationale |
|---|---|---|
| **D1** | **Tenancy: schema-ready, auth stubbed.** `tenant_id` in every table and in `thread_id` from day one; `current_tenant()` returns a constant. | Costs ~half a day now. Deferring means migrating every existing Postgres checkpoint's `thread_id` *and* altering both new tables. The research marks incremental tenancy as the highest-risk path. |
| **D2** | **Postgres and in-memory both, behind one Protocol**, with a shared contract test suite run against both. | Preserves the ~6-second offline test suite, which is a stated project constraint. The drift risk that normally makes dual implementations a bad idea is mitigated by the shared contract suite. |
| **D3** | **Async by default with a `?wait=` escape hatch.** `POST /cases` returns `202 {run_id, case_id}`; `?wait=true` awaits the run's completion future. | `?wait=` is a thin await on an existing future — it does **not** fork the execution path, so there is one code path to test. Keeps `scripts/demo_case.py` and the test suite readable. |
| **D4** | **`RunContext` now; graph topology unchanged.** Add `context_schema`; defer subgraph extraction and the `Command` refactor. | `RunContext` is required regardless — it is how `tenant_id` and actor identity reach nodes. The subgraph's payoff is voice-specific stages; build it when those stages exist, not speculatively. |

### D4 closes a real hole

The audit trail currently records `by=pack.gate_role` — the string `"compliance officer"` —
with **no user identity whatsoever**. For a compliance product where every gate decision is a
regulated judgment, that is a genuine defect, not a nicety. `RunContext.actor` fixes it.

---

## 3. Architecture

```
src/voxgate/service/
  db.py       NEW       AsyncConnectionPool + AsyncPostgresSaver, owned by FastAPI lifespan
  store.py    REWRITE   CaseStore Protocol + InMemoryCaseStore + PgCaseStore
  events.py   REWRITE   EventBus Protocol + InMemoryEventBus + PgEventBus
  runs.py     NEW       RunWorker: submit / execute / cancel, orphan recovery, multitask
  runner.py   REWRITE   async; delegates execution to RunWorker
  app.py      EDIT      lifespan, tenant dependency, 202 + ?wait=, SSE replaces WS
src/voxgate/graph/
  context.py  NEW       RunContext dataclass
  build.py    EDIT      context_schema=RunContext; nodes gain a runtime parameter
```

### 3.1 The load-bearing idea

**The `cases` table is a projection of graph state, never a second source of truth.**

`_sync()` continues to write it from `graph.get_state()`, exactly as today. The checkpointer
remains the sole owner of case truth. This is what makes two store implementations safe:
neither owns truth, so they cannot disagree about it — they can only disagree about *query
semantics*, which is what the contract test suite pins down.

### 3.2 Two existing defects fixed as a side effect

- **`recover_case` becomes unnecessary.** The index survives restarts, so
  `GET /cases/{id}` no longer 404s after a reboot. Closes `.paul/STATE.md` remaining-item #3.
  The method is deleted, not deprecated.
- **The deferred Task-7 finding stops applying.** `CaseStore.get()`/`.list()` currently return
  live references to internal dicts, so a caller mutating a returned case silently corrupts
  store state. Rows from Postgres come back as copies; `InMemoryCaseStore` must copy on read
  to match, and the contract suite asserts it.

---

## 4. Components

### 4.1 `db.py` — async persistence

```python
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async def open_pool(dsn: str) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        dsn, min_size=2, max_size=20, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    return pool
```

**`autocommit=True` and `prepare_threshold=0` are not optional.** They are what
`AsyncPostgresSaver.from_conn_string` sets internally, and pgbouncer-style poolers break
without them. `AsyncPostgresSaver` explicitly rejects `pipe` when given an
`AsyncConnectionPool`, so the pool is passed directly. `setup()` must be called explicitly on
first use — the docstring is emphatic that it is the caller's responsibility.

Also in this phase: `MemorySaver` → `InMemorySaver`. As of 1.2.10 the former is a
backwards-compatibility alias (`langgraph/checkpoint/memory/__init__.py:631`).

### 4.2 `context.py` — run context

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RunContext:
    tenant_id: str
    pack_id: str
    actor: str          # 'bot' | 'reviewer:<user_id>' | 'system'
    run_id: str
    settings: dict | None = None    # per-tenant threshold overrides, unused for now
```

Passed via the first-class `context=` kwarg on `ainvoke`/`astream`.

**Do not smuggle tenant identity through `config["configurable"]`.** It lands in every
checkpoint's metadata, and `config_schema` is deprecated since v0.6.0 with removal scheduled
for v2.0.0 — verified in `langgraph/graph/state.py`.

Node signatures become `(state, runtime)`. The `_audited` wrapper reads
`runtime.context.actor` into each audit entry.

### 4.3 What is deliberately *not* changing in the graph

Topology, nodes, edges, and routing functions are untouched. `after_validate`, `force_gate`,
and `after_gate` survive this phase unchanged. The interview subgraph extraction and the
`Command` refactor are deferred to the voice sub-project.

One known latent issue is therefore **carried forward, not fixed**: `reviewer_gate` hardcodes
`reask_fields: ["source_of_funds"]`, a `kyc-uae` field name sitting in platform code. It is
recorded here so it is not lost, and it is fixed by the `Command` refactor in the voice phase.

### 4.4 `store.py` — case index

```sql
CREATE TABLE cases (
  tenant_id   text NOT NULL,
  case_id     uuid NOT NULL,
  pack_id     text NOT NULL,
  thread_id   text NOT NULL,          -- 'tenant:case_id', matches checkpoints.thread_id
  status      text NOT NULL,
  risk_band   text,
  risk_prob   double precision,
  live_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
  interrupt   jsonb,
  error       text,
  seq         bigserial,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, case_id)
);
CREATE INDEX cases_queue_idx ON cases (tenant_id, status, seq DESC);
CREATE INDEX cases_pack_idx  ON cases (tenant_id, pack_id, seq DESC);
```

The `CaseStore` Protocol keeps today's shape (`get`, `list`, `upsert`) with `tenant_id` added
to every signature.

**The LangGraph `Store` API is deliberately not used here.** `store.search()` does key-value
filtering, not `ORDER BY risk_prob DESC WHERE status='awaiting_review'` with pagination.
`CaseStore.list()` is a reporting query and belongs in SQL. The `Store` API has real uses for
this project — screening-result caching, per-tenant reviewer precedents, false-positive
allowlists — but all are cross-case *memory*, not the work queue, and all are deferred.

### 4.5 `events.py` — pub/sub

`PgEventBus` uses Postgres `LISTEN`/`NOTIFY` with **one dedicated listener connection per
worker process**, fanned out in-process to subscribers.

Two hard constraints shape the design:

- **`pg_notify` caps payloads at 8000 bytes.** Notifications therefore carry
  `{case_id, kind, seq}` only, and the SSE handler reads the row. The current
  `{"kind": "state", "case": {...}}` payload shape would exceed this on any case with a full
  score waterfall and check results.
- **Never open a Postgres connection per browser client.** One listener per process; in-process
  fan-out to that process's subscribers.

```sql
CREATE TABLE events (
  tenant_id  text   NOT NULL,
  case_id    uuid   NOT NULL,
  seq        bigserial PRIMARY KEY,
  kind       text   NOT NULL,
  payload    jsonb  NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_case_idx ON events (tenant_id, case_id, seq);
```

The monotonic `seq` gives `Last-Event-ID` replay — the one genuinely hard capability the
licensed Agent Server provides, reproduced here in a table and a `WHERE seq > $1`.

**Retention:** events accumulate without bound in this phase. A retention policy is a known
follow-up, recorded in §8. It is not urgent at demo volume and adding a sweeper now would be
speculative.

**Multi-process caveat:** with more than one uvicorn worker, each process opens its own
listener and each receives every notification — which is correct, since each fans out only to
its own connected clients. Redis becomes worthwhile only when moving beyond one worker *box*,
not one worker process.

### 4.6 `runs.py` — the run worker

```python
async def submit(case_id, pack_id, tenant_id, payload=None, multitask="reject") -> str
```

An asyncio task per run, bounded by a semaphore. `POST` enqueues and returns
`202 {run_id, case_id, status: "pending"}`.

**Concurrency bound:** `VOXGATE_RUN_CONCURRENCY`, default **10**. Graph execution today is
CPU-bound and sub-millisecond, so the bound is nearly irrelevant now — it exists so the ceiling
is explicit and tunable *before* voice and Groq nodes make it matter. Revisit when a node does
real I/O.

```sql
CREATE TABLE runs (
  run_id     uuid PRIMARY KEY,
  tenant_id  text NOT NULL,
  case_id    uuid NOT NULL,
  status     text NOT NULL,          -- pending | running | succeeded | failed | cancelled
  error      text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX runs_case_idx  ON runs (tenant_id, case_id, created_at DESC);
CREATE INDEX runs_alive_idx ON runs (status) WHERE status IN ('pending', 'running');
```

**`multitask` is not optional.** The Pipecat bot will `PATCH` fields while a reviewer clicks
Approve on the same case — concurrent runs against one `thread_id` are a certainty, not an edge
case. Two policies are implemented:

- **`reject`** (default) → `RunInProgress` → HTTP **409**. The honest answer.
- **`interrupt`** → cancel the in-flight run, then start the new one. Safe because the
  checkpoint survives cancellation. This is the voice-reconnect path.

`enqueue` and `rollback` from the Agent Server's four-policy set are **not** implemented. No
identified use case; adding them would be speculative.

**Orphan recovery at boot:** every run left `running` or `pending` is reconciled against the
checkpointer. The reconciliation is **not** a blind re-submit, because a run row left `running`
has two very different possible causes:

```python
snap = await graph.aget_state(cfg)
if snap.tasks and any(t.interrupts for t in snap.tasks):
    # The graph reached an interrupt and is legitimately parked awaiting human
    # input. The run itself finished; only the status write was lost.
    await runs.set_status(run_id, "succeeded")
    await self._sync(case_id, pack_id, tenant_id)
else:
    # Killed mid-execution. Continue from the last checkpoint.
    # `None` input means "resume this thread", NOT "answer the interrupt with None".
    await self.submit(case_id, pack_id, tenant_id, payload=_CONTINUE)
```

`Command(resume=None)` would be **wrong** here — it answers a pending `interrupt()` with a
`None` payload, which crashes the node expecting `payload["fields"]`. Continuing from a
checkpoint is `ainvoke(None, config)`. `submit()` therefore distinguishes "no payload, continue"
(`_CONTINUE` sentinel → `None` input) from "resume an interrupt with this payload"
(`Command(resume=payload)`).

LangGraph's checkpointer makes a killed run resumable, so this is a query and a loop — not a
broker.

**Graceful shutdown:** `RunControl` (`langgraph/runtime.py:79`) is wired to SIGTERM so a rolling
deploy finishes the current superstep, checkpoints, and exits cleanly rather than dying
mid-case.

**Deliberately not Celery or arq.** A distributed broker is correct at "many machines, runs must
survive a pod kill mid-execution." VoxGate is not there. `submit()` is the seam where a broker
drops in later without an API change.

### 4.7 `app.py` — HTTP surface

| Route | Change |
|---|---|
| `POST /cases` | Returns **202** `{run_id, case_id, status}`. `?wait=true` awaits the run's completion future and returns 201 with the full case. |
| `POST /cases/{id}/interview-result` | Returns 202 + `run_id`; same `?wait=` support. |
| `POST /cases/{id}/decision` | Same. |
| `GET /cases/{id}/events` | **SSE** (`text/event-stream`), honours `Last-Event-ID`. |
| `WS /cases/{id}/events` | **Removed.** |
| `GET /runs/{run_id}` | **New.** Run status polling. |
| `POST /cases/{id}/recover` | **Not built** — made unnecessary by §3.2. |
| `GET /packs`, `GET /cases`, `GET /cases/{id}`, `PATCH /cases/{id}/fields` | Unchanged except for the tenant dependency. |

**`?wait=true` semantics:** it awaits the run's completion future with a timeout (default 30 s,
configurable). On timeout it returns **202** with the `run_id` rather than erroring — the run
continues; only the client's patience expired. This keeps the escape hatch honest: it is a
convenience, never a correctness guarantee.

**Tenant dependency:**

```python
async def current_tenant(request: Request) -> str:
    return "default"                      # swap for JWT / API-key resolution later

async def owned_case(case_id: str, tenant: str = Depends(current_tenant), ...):
    case = await store.get(tenant, case_id)     # tenant_id is IN the WHERE clause
    if case is None:
        raise HTTPException(404, "case not found")   # 404, never 403 — no existence oracle
    return case
```

Returning 404 rather than 403 for a case belonging to another tenant is deliberate: 403 confirms
the case exists, which is an information leak.

**The WebSocket is removed, not deprecated.** Nothing consumes it — the dashboard has no JS.
Keeping it would preserve the exact thread-blocking behaviour this phase exists to eliminate, in
a supported endpoint. WebSocket returns later for Pipecat signalling, where bidirectional
communication is genuinely required.

---

## 5. Data flow

```
POST /cases ─→ current_tenant() ─→ RunWorker.submit() ─→ 202 {run_id}
                                        │
                                        ↓  asyncio task, semaphore-bounded
                        graph.astream(input, config,
                                      context=RunContext(tenant, pack, actor, run_id),
                                      stream_mode=["updates", "custom"],
                                      durability="sync")
                                        │
                        ┌───────────────┴───────────────┐
                        ↓                               ↓
                 _sync() → cases table          bus.publish() → events table
                  (projection of                        │        + pg_notify(8KB max)
                   graph.get_state())                   ↓
                                              SSE subscribers ← replay by seq
```

`thread_id = f"{tenant_id}:{case_id}"`. `checkpoints.thread_id` is `TEXT`, so the prefix is
safe; keep the composite under 255 characters.

**`durability="sync"` at every invoke site.** The default is `"async"` — verified at
`langgraph/pregel/main.py:2603` — which writes checkpoints concurrently with the next step and
can lose the last checkpoint on a crash mid-step. Acceptable for a chatbot; not for a regulated
KYC decision with an audit trail. The cost is one extra Postgres round-trip per superstep on a
graph running roughly a dozen supersteps per case.

**Error handling** stays where it already works. `CaseRunner`'s `try/except Exception` →
`status="needs_attention"` is an established trust boundary — a deliberate architectural ruling
recorded in `.paul/STATE.md` under parked findings, where graph-level guards were rejected
because the runner already owns this boundary. That ruling stands.

What the worker adds is **run-level status**, so a failure is attributable to a specific run
rather than smeared onto the case. Per-node `error_handler` and `TimeoutPolicy` are deferred to
the perf-polish phase.

---

## 6. Testing

The suite must stay green at **54 passed, 1 skipped**, offline, in roughly 6 seconds.

### 6.1 Contract suites — the drift mitigation

The one real objection to dual implementations is silent divergence. It is answered directly:
**one shared contract test suite per Protocol, parameterized over both implementations.**

```python
@pytest.fixture(params=["memory", "postgres"])
def store(request): ...        # postgres param skips without VOXGATE_TEST_DB
```

Every behavioural guarantee — ordering, filtering, copy-on-read, tenant isolation — is asserted
once and runs against both. An implementation that drifts fails the suite.

### 6.2 New tests the research flags as missing and likely to bite

1. **Concurrent-run rejection.** Two resumes against one `case_id`; assert one gets 409. Easy
   to ship broken.
2. **Durability actually mattering.** `durability="exit"` with a mid-graph kill leaves no
   intermediate checkpoint; `"sync"` does. This is the test that justifies the setting, and it
   is the on-camera demo beat.
3. **Orphan recovery, both branches.** (a) A run killed mid-execution is continued from its
   checkpoint and completes. (b) A run whose graph is parked at an interrupt is marked
   `succeeded` and **not** re-executed — asserting specifically that the interrupt is not
   answered with a `None` payload, which is the failure mode a naive re-submit would cause.
4. **SSE replay.** Reconnect with `Last-Event-ID` and assert no gap and no duplication.
5. **Tenant isolation.** Tenant A cannot read tenant B's case; the response is 404, not 403.

### 6.3 Existing tests requiring changes

- `tests/test_api.py` — async client; 202 assertions or `?wait=true`; SSE instead of WS.
- `tests/test_runner.py` — `pytest.mark.asyncio` throughout.
- `tests/test_graph*.py` — nodes gain a `runtime` parameter; invocations pass `context=`.
- `tests/integration/test_postgres_resume.py` — extended to cover orphan recovery.

Graph *topology* tests are untouched, which is the direct benefit of decision D4.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Async conversion touches every service module at once | Medium | Phase it: async spine lands first with in-memory store/bus and existing route shapes, so it is verifiable in isolation before the index and worker land. |
| Dual implementations drift | Medium | Shared contract suites (§6.1). This is the whole answer. |
| `pg_notify` 8000-byte cap silently truncating | High if missed | Payloads are `{case_id, kind, seq}` by construction; a test asserts the notify payload stays under 7900 bytes. |
| SSE behind proxies/buffering | Low | `X-Accel-Buffering: no`, explicit flush, heartbeat comments. |
| `?wait=` becoming load-bearing for real clients | Low | Documented as a convenience with a timeout that degrades to 202. Never a correctness guarantee. |
| Events table unbounded growth | Low now | Recorded as follow-up §8. Not urgent at demo volume. |

---

## 8. Known follow-ups, recorded not built

- Events-table retention policy.
- Per-node `error_handler` and `TimeoutPolicy` for graceful single-check degradation.
- `CachePolicy` with a custom `key_func` — **the default key function hashes the `audit`
  reducer, so the hit rate would be exactly zero.** Silent failure; must not be added naively.
- OpenTelemetry + Prometheus. `_audited` already computes `duration_ms` per node, so the
  histogram is nearly free when wanted.
- Redis, when moving beyond one worker box.
- The `reask_fields: ["source_of_funds"]` leak in `reviewer_gate` (§4.3).
- Real authentication behind `current_tenant()`.

---

## 9. Definition of done

1. `uv run pytest -q` → **54 passed, 1 skipped**, offline, no Docker required.
2. `VOXGATE_TEST_DB=... uv run pytest` → contract suites pass against Postgres, plus the five
   new tests in §6.2.
3. A case survives a full process restart and `GET /cases/{id}` returns it — **no
   `recover_case` call**.
4. Two concurrent runs against one case: one succeeds, one gets 409.
5. `scripts/demo_case.py` runs end to end unchanged in behaviour, using `?wait=true`.
6. An SSE client reconnecting with `Last-Event-ID` observes no gap and no duplicate.
7. No route blocks a worker thread on graph execution.
