# LangGraph Production Upgrade — demo-flat → multi-tenant, multi-use-case

**Date:** 2026-08-07
**Method:** Read the installed `langgraph` 1.2.10 source in `.venv` line by line, plus PyPI
metadata, plus current official docs. Every signature below was verified against installed
source, not just documentation — and in three places the source contradicts the docs.

This is **Wave 2**: the production/platform layer. Wave 1 (audit reducer, richer interrupt
payloads, per-check `RetryPolicy`) already shipped — see
`docs/design/2026-08-06-graph-upgrade-design.md`.

---

## The three findings that are not in any documentation

Leading with these because each one is a silent failure mode.

1. **`durability` defaults to `"async"`, not `"sync"`.** Checkpoints are written concurrently
   with the next step, so a crash mid-step can lose the last checkpoint. For a regulated KYC
   decision that is a compliance incident, not a latency win.
2. **`CachePolicy`'s default key function hashes the entire node input — including the
   `audit` reducer list, which grows on every node execution.** The cache key is therefore
   different every time and **the hit rate is exactly zero**. You must supply `key_func`. The
   failure is silent: no error, just no speedup.
3. **`langgraph_sdk.Auth` is inert outside the licensed server.** It is a declarative
   registry with no enforcement of its own; only the Elastic-2.0 Agent Server reads it.

---

## 1. Version check — already current

Verified against the PyPI JSON API and the installed `.venv` on 2026-08-07:

| Package | Locked | Latest | Released | License |
|---|---|---|---|---|
| `langgraph` | 1.2.10 | **1.2.10** | 2026-07-28 | MIT |
| `langgraph-checkpoint` | 4.1.1 | 4.1.1 | 2026-05-22 | MIT |
| `langgraph-checkpoint-postgres` | 3.1.1 | **3.1.1** | 2026-07-30 | MIT |
| `langgraph-sdk` | 0.4.2 | 0.4.2 | 2026-06-01 | MIT |
| `langchain-core` | 1.5.3 | — | — | MIT |
| `langgraph-cli` | not installed | 0.4.31 | 2026-07-10 | MIT |
| **`langgraph-api`** | — | **0.12.0** | 2026-08-05 | **Elastic-2.0** |
| **`langgraph-runtime-inmem`** | — | 0.32.0 | 2026-08-05 | **Elastic-2.0** |

**No upgrade needed.** Two housekeeping items:

- `pyproject.toml` floors are badly stale (`langgraph>=0.4`, `langgraph-checkpoint-postgres>=2.0`).
  Those ranges permit installing pre-`Command`, pre-`context_schema` versions. Raise to
  `langgraph>=1.2.10,<2` and `langgraph-checkpoint-postgres>=3.1,<4`.
- `MemorySaver` is now just an alias — `langgraph/checkpoint/memory/__init__.py:631`:
  `MemorySaver = InMemorySaver  # Kept for backwards compatibility`. Rename in tests and
  `app.py`.

**Docs URLs moved.** `langchain-ai.github.io/langgraph/*` is dead or redirecting. Canonical is
now `docs.langchain.com/oss/python/langgraph/*`. "LangGraph Platform" was renamed **"LangSmith
Deployment"**, and "LangGraph Server" → **"Agent Server"**.

---

## 2. Structural upgrades

`add_node` in 1.2.10, verified from `langgraph/graph/state.py`:

```python
def add_node(self, node, *, defer=False, metadata=None, input_schema=None,
             retry_policy=None, cache_policy=None, error_handler=None,
             destinations=None, timeout=None) -> Self
```

`error_handler` and `timeout: TimeoutPolicy` are new and essentially undocumented. Both are
directly useful here.

### 2a. Extract the interview loop into a subgraph — **do this first**

Highest-value structural change. Today the re-ask loop is tangled into the top-level graph via
`after_validate`, which returns *either* `"interview"`, *or* `"force_gate"`, *or* a list of
check node names — **three unrelated concerns in one function**.

A compiled subgraph sharing `CaseState` drops in as a plain node. `compile()` with no
checkpointer **inherits the parent's** (verified: `Checkpointer = None | bool |
BaseCheckpointSaver`, `None` inherits). `interrupt()` inside bubbles to the parent, and
`Command(resume=...)` on the parent routes back in.

```python
# src/voxgate/graph/interview.py  (new)
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from pydantic import ValidationError
from .state import CaseState

def build_interview_subgraph(pack, *, max_reasks: int = 2):
    """Reusable ask→validate→re-ask loop. Same state schema as the parent,
    so it composes as a node and shares fields/audit/reask_count."""
    g = StateGraph(CaseState)

    def ask(state: CaseState) -> Command:
        reask = state.get("reask_fields", [])
        schema_fields = list(pack.schema_model.model_fields)
        payload = interrupt({
            "type": "interview",
            "reask_fields": reask,
            "reask_hints": {f: pack.reask_hints[f] for f in reask if f in pack.reask_hints},
            "fields_so_far": state.get("fields", {}),
            "field_errors": {f: state.get("field_errors", {}).get(f) for f in reask},
            "attempt": state.get("reask_count", 0),
            "max_attempts": max_reasks,
            "fields_validated": [f for f in schema_fields
                                 if f not in reask and f in state.get("fields", {})],
        })
        return Command(
            update={"fields": {**state.get("fields", {}), **payload["fields"]},
                    "field_confidence": payload.get("confidence", {}),
                    "status": "processing", "reask_fields": []},
            goto="validate",
        )

    def validate(state: CaseState) -> Command:
        try:
            clean = pack.schema_model(**state["fields"]).model_dump()
        except ValidationError as e:
            errs = {err["loc"][0]: err["msg"] for err in e.errors() if err["loc"]}
            n = state["reask_count"] + 1
            if n > max_reasks:
                return Command(update={"force_review": True, "reask_count": n,
                                       "field_errors": errs}, goto=END)
            return Command(update={"reask_fields": sorted(errs), "reask_count": n,
                                   "field_errors": errs}, goto="ask")
        return Command(update={"fields": clean, "reask_fields": [], "field_errors": {}},
                       goto=END)

    g.add_node("ask", ask, destinations=("validate",))
    g.add_node("validate", validate, destinations=("ask", END))
    g.add_edge(START, "ask")
    return g.compile()   # checkpointer inherited from parent
```

**Why it helps VoxGate specifically:** `medium_reask → interview` and the validation re-ask are
two different loops that today hit the same top-level node. With the subgraph, `medium_reask`
sets `reask_fields` and re-enters the *subgraph*, which owns the cap. And when Pipecat lands,
voice-specific stages (confidence check, in-call confirm, transcript capture) go **inside** the
subgraph — the outer graph never changes.

**Cost:** `graph.get_graph().nodes` in `tests/test_graph.py:24` will no longer show the
interview internals. That test needs updating.

### 2b. `Command` for update+goto — yes

Collapses node + routing function into one place. Concretely it **deletes `force_gate`,
`after_validate`, and `after_gate`** from `build.py`. `graph=Command.PARENT` also exists
(`langgraph/types.py:24986`), letting a subgraph node route in the parent.

It also fixes a latent bug: the current `reviewer_gate` hardcodes
`reask_fields: ["source_of_funds"]` — **a kyc-uae field name sitting in platform code**. With
`Command` you take it from the reviewer's payload.

Use `destinations=(...)` on `add_node` for these. Purely for `get_graph()` rendering — the
docstring is explicit that it *"doesn't have any effect on the graph execution"* — but you want
Studio and mermaid output to stay readable.

### 2c. `Send` for dynamic fan-out — **no at the check level, yes one level down**

Pushing back on the assumption here. `after_validate` already returns
`[_node_name(c) for c in pack.checks]` — that **is** dynamic fan-out over a static node set, and
it is strictly better than `Send`, because named nodes give you per-check `retry_policy`,
`cache_policy`, `timeout`, individual trace spans, and readable Studio graphs.

`Send("run_check", …)` would collapse all checks into one node name and throw all of that away.
Keep named nodes; make the *subset* dynamic:

```python
def after_interview(state: CaseState):
    if state.get("force_review"):
        return "force_gate"
    return [_node_name(c) for c in pack.checks
            if getattr(c, "applies_when", _always)(state["fields"])]
```

`Send` earns its place **inside** a check, where cardinality is genuinely runtime-determined —
screening one name against N sanctions lists × M transliteration variants. **Defer** until
`NameMatcher` is actually the bottleneck.

### 2d. `CachePolicy` — yes, but the default key function is a trap

```python
# langgraph/_internal/_cache.py:26
def default_cache_key(*args, **kwargs) -> str | bytes:
    return pickle.dumps((_freeze(args), _freeze(kwargs)), protocol=5, fix_imports=False)
```

It hashes the entire node input, which includes `audit` — a reducer list that grows on **every
node execution**. Hit rate: zero. Supply `key_func`:

```python
import hashlib, json
from langgraph.cache.memory import InMemoryCache
from langgraph.types import CachePolicy, RetryPolicy, TimeoutPolicy

def _check_key(check_name: str):
    def key_func(state: CaseState) -> bytes:
        return hashlib.sha256(json.dumps(
            {"check": check_name, "fields": state.get("fields", {})},
            sort_keys=True, default=str).encode()).digest()
    return key_func

for c in pack.checks:
    name = _node_name(c)
    g.add_node(name, _audited(name, make_check_node(c), clock),
               retry_policy=RetryPolicy(max_attempts=3,
                                        retry_on=(TimeoutError, ConnectionError)),
               cache_policy=CachePolicy(key_func=_check_key(name), ttl=900),
               timeout=TimeoutPolicy(run_timeout=20.0))
graph = g.compile(checkpointer=checkpointer, cache=InMemoryCache())
```

**Caveat:** `langgraph/cache/` ships only `memory` and `redis` — **there is no Postgres cache**.
Node caching is per-process unless you add Redis.

**Second caveat:** a cache hit skips the wrapped function entirely, so `_audited` writes no
entry. Arguably correct (nothing happened) but it will surprise you reading an audit trail.
Emit a synthetic `cached=true` entry from the fan-in node if that matters.

### 2e. `RetryPolicy` — already there, tune it

Defaults from source: `initial_interval=0.5, backoff_factor=2.0, max_interval=128.0,
max_attempts=3, jitter=True`. The known deviation in `.paul/STATE.md` (RuntimeError not
retried) is correct and by design — `default_retry_on` targets connection/5xx classes.

Add the new `error_handler=` param instead of relying on `CaseRunner`'s blanket
`except Exception → needs_attention`. That lets a **single** failed check degrade gracefully
(record `status="error"`, continue to scoring, force the reviewer gate) rather than killing the
whole case — which is what you actually want in compliance.

### 2f. Durability — set `"sync"` explicitly

```python
Durability = Literal["sync", "async", "exit"]        # langgraph/types.py:2322
# main.py:2603 — durability = config.get(CONF, {}).get(CONFIG_KEY_DURABILITY, "async")
```

It is a kwarg on `invoke`/`ainvoke`/`stream`/`astream`, **not** on `compile()`.

**Use `"sync"`.** Cases are low-volume and high-value; each is a regulated decision with an
audit trail. The overhead is one extra Postgres round-trip per superstep on a graph running a
dozen supersteps per case. Use `"exit"` only in unit tests.

### 2g. Deferred nodes (`defer=True`) — skip for now

Your `score` fan-in already works because all check branches are one node long. `defer=True`
matters only with *asymmetric* branch lengths.

Two caveats first: **langgraph#6005 (open, unanswered)** — with **multiple** deferred nodes, a
deferred node can execute, then re-execute. A **single** deferred fan-in node is the safe case.
(#5182 is only a `get_graph()` rendering artifact.) So if check branches ever become
multi-node, add `defer=True` to `score` **only**, never a second one.

### 2h. `interrupt()` versus static breakpoints — keep `interrupt()`

`interrupt_before`/`interrupt_after` pause between nodes with no payload. Your gates hand the
client structured payloads (`reask_hints`, `score_waterfall`, `flagged_checks`). Keep them.

**The thing to internalize**, from the 1.2.10 docstring:

> *"The graph resumes from the start of the node, **re-executing** all logic."*

So **never put a side effect before an `interrupt()` in the same node.** `interview()` and
`reviewer_gate()` are clean today (pure reads before the interrupt). The moment you add "send
the applicant an SMS" or "write to an external audit log", it must live in a *separate node
after* the interrupt, or it fires once per resume.

Also new: `langgraph/runtime.py:79` **`RunControl`** — a run-scoped cooperative drain signal
(`request_drain(reason)`, `runtime.execution_info`). Wire it to SIGTERM so a rolling deploy
finishes the current superstep, checkpoints, and exits cleanly instead of dying mid-case.

---

## 3. The sync-invoke problem, and the LangGraph Server question

### Verdict: do not adopt LangGraph Server. It is not free for production.

This is the most consequential finding, and it is not close.

`langgraph-api` (the server runtime) is **Elastic License 2.0** — confirmed from PyPI metadata
(`license: Elastic-2.0`) and its README. So is `langgraph-runtime-inmem`. Neither has a source
repository in `langchain-ai/langgraph`; they are PyPI/Docker artifacts only. The MIT
`langgraph-cli[inmem]` extra transitively installs both, **so `langgraph dev` already runs
closed-source ELv2 code.**

Self-hosting requirements, from `docs.langchain.com/langsmith/deploy-standalone-server`:

- `LANGSMITH_API_KEY` — required
- `LANGGRAPH_CLOUD_LICENSE_KEY` — *"used to authenticate ONCE at server start up"*
- *"Egress to `https://beacon.langchain.com` … required for license verification and usage
  reporting if not running in air-gapped mode"* — and per `/langsmith/self-host-egress` the
  billing telemetry **cannot be disabled** without a negotiated air-gapped contract.

LangChain staff, on the official forum (forum.langchain.com/t/question-about-the-license/2242):
*"Full self-hosting of production workloads currently requires an enterprise license, though
you can run the server with a valid LangSmith API key for lighter workloads."* Asked to define
"lighter workloads": *"I mean development and testing purposes!"*

ELv2 also forbids providing the software *"to third parties as a hosted or managed service"* —
which is precisely the shape of a multi-tenant compliance platform.

Pricing (langchain.com/pricing, 2026): Developer $0 (1 seat, 5k traces/mo), **Plus $39/seat/mo**
(required for Cloud deployment), **Enterprise custom** (required for self-hosted). Note the
2025-era "Self-Hosted Lite, free up to 1M nodes executed" tier **no longer appears**, and
github.com/langchain-ai/docs#471 asking which limit applies to which tier was **closed with no
answer**. Do not plan around it.

For a project demoing a *regulated Gulf compliance* workflow, a runtime that phones home to a
US vendor for usage reporting — and cannot be told not to — is an actively bad story to tell in
the demo.

**What you give up** (all real work, all ELv2): Postgres-backed task queue with exactly-once run
state; `multitask_strategy` double-texting (`enqueue|reject|interrupt|rollback`); cron; resumable
SSE via Redis Streams with `Last-Event-ID`; TTL sweepers; ~45 REST routes; auth filter injection;
Studio; webhooks. Plus **`useStream` from `@langchain/langgraph-sdk/react` will not work against
your FastAPI** — it speaks the Agent Server protocol.

You need maybe 30 % of that. Build it — roughly 700 lines.

### The replacement: async graph + background run worker

`CaseRunner.start_case` currently blocks a FastAPI thread on a synchronous `.invoke()` and, per
the project's own parked finding, only gets away with it because *"no LLM/network-calling nodes
exist yet."* **That expires the moment Pipecat or Groq lands.**

**1. Go fully async.** `AsyncPostgresSaver` + a pool (the class explicitly rejects `pipe` with
`AsyncConnectionPool`):

```python
# src/voxgate/service/db.py  (new)
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

async def open_pool(dsn: str) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        dsn, min_size=2, max_size=20, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    return pool
```

`prepare_threshold=0` and `autocommit=True` are **not optional** — they are what
`from_conn_string` sets, and pgbouncer-style poolers break without them. `setup()` *"MUST be
called directly by the user the first time."*

**2. Runs become first-class and non-blocking.** The handler enqueues and returns `202` with a
run id; a worker executes. An in-process asyncio worker over a Postgres-backed run queue is the
honest 80 %, and it upgrades to a separate process later without an API change.

```python
async def submit(self, case_id, pack_id, tenant_id, payload=None, multitask="reject") -> str:
    if case_id in self._tasks and not self._tasks[case_id].done():
        if multitask == "reject":
            raise RunInProgress(case_id)        # → HTTP 409, the honest default
        if multitask == "interrupt":
            self._tasks[case_id].cancel()       # checkpoint survives; safe to re-enter
    ...
    async for chunk in graph.astream(
            inp, cfg, context=RunContext(...),
            stream_mode=["updates", "custom"],
            durability="sync", version="v2", subgraphs=True):
        await self.bus.publish(case_id, chunk)
```

**`multitask` is not optional — you will hit double-texting**: the Pipecat bot `PATCH`es fields
while the reviewer clicks Approve. Agent Server gives four policies; you need `reject` (409)
plus `interrupt` for voice reconnect. ~15 lines.

**3. Do not reach for Celery/arq yet.** LangGraph's checkpointer already makes a killed run
*resumable* — a supervisor that re-submits for any run left `running` at boot recovers
everything. Add arq later if you genuinely run more than one worker box; `submit()` is the seam.

---

## 4. What replaces `CaseStore` and `EventBus`

They solve three *different* problems, and LangGraph's `Store` API only solves one. Be precise:

| Concern | Today | Replacement |
|---|---|---|
| Case workflow state | `PostgresSaver` ✅ | unchanged — already durable |
| Case **index** (list/filter/sort queue) | `CaseStore` dict ❌ | **your own Postgres table** |
| Live event fanout | `EventBus` dict ❌ | **Postgres LISTEN/NOTIFY** (Redis later) |
| Cross-thread long-term memory | — | LangGraph `Store` (new capability) |

### The case index: a plain table, not the Store API

Resist using `BaseStore` for the queue. `store.search()` does key-value filtering, not
`ORDER BY score DESC WHERE status='awaiting_review' AND pack_id=$1` with pagination.
`CaseStore.list()` is a reporting query — write SQL.

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

This is a **projection** of graph state, not a second source of truth — `_sync()` keeps writing
it from `get_state()`. Two things fall out for free: **`recover_case` becomes unnecessary** and
STATE.md remaining-item #3 ("after restart `GET /cases/{id}` 404s") is closed, because the index
survives. It also fixes the deferred Task-7 finding that `CaseStore.get()` returns live internal
dict references — rows come back as copies.

### Pub/sub: Postgres LISTEN/NOTIFY, one listener per worker process

You already run Postgres; adding Redis for a demo-scale bus is unearned complexity. Two hard
constraints:

- **`pg_notify` payload cap is 8000 bytes.** Notify with `{case_id, kind, seq}` only and let the
  SSE handler read the row. The current `{"kind":"state","case":{...}}` payloads would blow past
  it.
- **Never open one Postgres connection per browser client.** One dedicated listener connection
  per worker process, fanned out in-process.

Add an `events` table with a monotonic `seq` so a reconnecting client can replay via
`Last-Event-ID`. That is the one genuinely hard thing Agent Server provides (Redis Streams +
`stream_resumable`), and `WHERE case_id=$1 AND seq > $2` is a perfectly good 90 %.

**Upgrade trigger for Redis:** more than one worker box, or wanting `RedisCache` for
cross-process node caching. Not before.

### LangGraph `Store` — a new capability, not a replacement

Verified API: `put(namespace: tuple[str,...], key, value, index=None, *, ttl=None)`, `get`,
`search(namespace_prefix, /, *, query=None, filter=None, limit=10, offset=0)`, `delete`,
`list_namespaces`. `PostgresStore`/`AsyncPostgresStore` create `store` and `store_vectors`;
semantic search needs pgvector and an embedder.

Good fits — cross-*case* knowledge the thread-scoped checkpointer cannot hold: screening-result
caching keyed on name hash, per-tenant reviewer decision precedents, false-positive allowlists
an officer builds over time, per-tenant pack config overrides. **Defer** — real value, zero
urgency.

---

## 5. Multi-tenancy

The design spec explicitly lists auth/multi-tenancy as out of scope for v1. Smallest correct
thing, in four layers:

**1. Thread ID namespacing.** `checkpoints.thread_id` is `TEXT`, so
`f"{tenant_id}:{case_id}"` (keep under 255 chars). Defense in depth, **not** the security
boundary.

**2. `context_schema` + `Runtime` — and note `config_schema` is deprecated.** From
`langgraph/graph/state.py`: *"`config_schema` Deprecated — deprecated in v0.6.0 and support will
be removed in v2.0.0. Please use `context_schema` instead."* `invoke`/`stream`/`ainvoke`/
`astream` all take a first-class `context=` kwarg now. **Don't smuggle tenant identity through
`config["configurable"]`** — it lands in every checkpoint's metadata.

```python
@dataclass(frozen=True)
class RunContext:
    tenant_id: str
    pack_id: str
    actor: str          # 'bot' | 'reviewer:<user_id>' | 'system'
    run_id: str
    settings: dict | None = None
```

This is a correctness win independent of tenancy: **the audit trail currently records
`by=pack.gate_role` ("compliance officer") with no user identity.** For a compliance product
that is a hole.

**3. The actual boundary — a FastAPI dependency with `WHERE tenant_id`.** Return **404, never
403**, so there is no existence oracle.

**4. Postgres RLS — possible but skip it on checkpoint tables.** You'd need it on `checkpoints`,
`checkpoint_blobs`, `checkpoint_writes`, plus `store`/`store_vectors`, and `SET app.tenant_id`
must be issued per-checkout on a pooled connection — easy to get wrong and it **silently fails
open**. Do RLS on *your* `cases`/`events` tables where the tenant column is explicit. If a
tenant ever demands real isolation, give them a **separate Postgres schema** — clean, auditable,
and explainable to a regulator. Scales to a few hundred tenants.

---

## 6. Multi-use-case: packs → graph structure

**Keep one compiled graph per pack. Do not build one parameterized mega-graph.**

The current `{pid: build_graph(p, checkpointer) …}` is right, and the reason is structural:
check node *names* derive from pack contents. A single graph would either union every pack's
nodes (leaky, unreadable in Studio) or collapse checks into one `Send` node (losing per-check
retry/cache/timeout). Compiled graphs are cheap — built once at startup.

What to change is **how** they are built. Today `build_graph` is a 190-line closure where
platform policy and pack policy are interleaved. Split it:

```
graph/
  state.py       CaseState
  context.py     RunContext
  interview.py   build_interview_subgraph(pack)     ← reusable across all packs
  stages.py      platform stages: intake, score, route, gates, finalize
  build.py       assemble(pack) -> CompiledStateGraph
```

Then let a pack **declare** topology rather than fork platform code (additive to the existing
`Pack` dataclass and `pack.yaml`):

```python
gate_mode: str = "human"                 # "human" | "auto" | "dual" (maker-checker)
stages: list[str] = []                   # optional pack-supplied nodes
check_predicates: dict[str, Callable] = {}
escalation: dict | None = None
```

This is what makes "adding a pack touches zero platform code" survive contact with real packs:
FNOL wants a *conditional* fraud-investigation stage; loan-intake wants a maker-checker double
gate; a v2 patient-intake wants no gate at all under a triage threshold. **Today all three would
require editing `build.py`.** Run `tests/pack_conformance.py` against a synthetic pack exercising
each `gate_mode` to keep the claim honest.

---

## 7. Streaming — and retiring the hand-rolled bus

**Seven stream modes** in 1.2.10, not five: `values`, `updates`, `messages`, `custom`,
`checkpoints`, `tasks`, `debug`. `subgraphs=True` prefixes chunks with a namespace tuple —
essential once the interview is a subgraph. `version="v2"` gives uniformly-shaped chunks with a
`type` field.

`get_stream_writer()` (exported from `langgraph.config`) replaces most of what `EventBus.publish`
did by hand:

```python
from langgraph.config import get_stream_writer

def make_check_node(check):
    def node(state: CaseState):
        writer = get_stream_writer()
        writer({"phase": "check", "check": check.check_name, "state": "running"})
        result = check(state["fields"]).model_dump()
        writer({"phase": "check", "check": check.check_name,
                "state": "done", "status": result["status"]})
        return {"check_results": [result]}
    return node
```

Now the dashboard's live pipeline SVG is driven **by the graph itself** rather than by
`runner._sync` reconstructing state after the fact.

**SSE over WebSocket for the Next.js UI.** The current `WS /cases/{id}/events` does
`asyncio.to_thread(bus.wait, …)` with a 1 s poll — **a thread per connected client**. SSE is
server→client only, reconnects automatically with `Last-Event-ID`, passes proxies without
upgrade headaches, and is one line in the browser. Keep WebSocket only for Pipecat signalling,
where bidirectional is genuinely needed.

**Next.js note:** `useStream` from `@langchain/langgraph-sdk/react` expects an Agent Server and
**will not work against your FastAPI**. Use plain `EventSource` (or `@microsoft/fetch-event-source`
if you need POST+headers) and a small `useCase(caseId)` hook — ~60 lines, and you keep control of
the payload shape, which matters since your events carry score waterfalls, not chat messages.

---

## 8. Observability — skip LangSmith, go OTel

**LangSmith tracing is off by default in the library and costs nothing to leave off.** The
`langsmith` package is installed transitively but is inert until `LANGSMITH_TRACING=true`. (The
Agent Server flips this default to `true` — another reason not to adopt it.)

Recommended, free, self-hosted:

```bash
LANGSMITH_TRACING=true
LANGSMITH_TRACING_MODE=otel          # current form; LANGSMITH_OTEL_ONLY is legacy
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_SERVICE_NAME=voxgate
```

In `otel` mode **no LangSmith API key is required** and no LangSmith REST calls are made.

Two source-verified corrections to the official docs: (a) `LANGSMITH_TRACING_MODE`
(`langsmith|otel|hybrid`) now takes precedence over `LANGSMITH_OTEL_ENABLED`/`_ONLY`; (b) the
docs claim LangSmith headers are added automatically — **false**. If you set
`OTEL_EXPORTER_OTLP_HEADERS` your headers *replace* `x-api-key`, so you will not leak a key to
your own collector.

Target: **Langfuse** (MIT, self-hostable, native OTLP, LangGraph callback handler) is the closest
LangSmith substitute and keeps the "look, full traces" demo beat without a vendor.

**Metrics, not just traces.** `_audited` already computes `duration_ms` per node. Emit it as a
Prometheus histogram labeled `{pack_id, node, status_after}` for node-level p50/p95, plus
counters for `cases_by_status`, `reask_loops`, `needs_attention_total`, `check_retries_total`.
`prometheus-fastapi-instrumentator` at `/metrics`. Costs nothing.

---

## 9. Testing

Four additions, in value order:

1. **Test the interview subgraph in isolation** — the concrete payoff of §2a. No check data, no
   scorecard, no Postgres.
2. **Assert on interrupts via `snap.interrupts`**, and add `subgraphs=True` to any `get_state`
   used for assertions once the subgraph lands (interrupts bubble with a namespace). Assert on
   `Interrupt.id` — it is stable and it is what `Command(resume={id: value})` keys on.
3. **Test durability for real.** Run with `durability="exit"` and kill mid-graph → no
   intermediate checkpoint; run with `"sync"` → checkpoint present. That test justifies the
   setting and it is the on-camera demo beat. Parameterize the checkpointer fixture over
   `InMemorySaver` and `AsyncPostgresSaver` — LangGraph's own suite does exactly this.
4. **Two currently-untested things that will bite:**
   - **Cache key correctness** — assert a second run with identical `fields` but a longer
     `audit` list *hits* the cache. Without the custom `key_func` it will not, silently.
   - **Concurrent-run rejection** — fire two resumes at the same `case_id`, assert one gets 409.
     Very easy to ship broken.

---

## 10. Migration plan

Effort assumes one engineer familiar with the codebase. S ≈ ≤1 day, M ≈ 2–3 days, L ≈ 4–5 days.

| # | Phase | What | Effort | Risk |
|---|---|---|---|---|
| **0** | Pin + rename | `pyproject` floors → `langgraph>=1.2.10,<2`; `MemorySaver`→`InMemorySaver`; `durability="sync"` at the 3 `.invoke()` sites | **S** | none |
| **1** | **Async spine** | `AsyncPostgresSaver` + pool; `ainvoke`/`astream`; FastAPI lifespan owns the pool. Graph unchanged | **M** | low — mechanical |
| **2** | Graph restructure | Extract `interview.py`; `Command` replaces 3 routing fns; `destinations=`; `context_schema=RunContext`; `error_handler` | **M** | medium — update `test_graph.py:24` |
| **3** | **Postgres case index** | `cases` + `events` tables; `PgCaseStore`. Deletes `recover_case`, closes STATE.md item #3 | **M** | low — same interface |
| **4** | PgEventBus + SSE | LISTEN/NOTIFY, one listener per process; SSE with `Last-Event-ID` replay | **M** | medium — the 8000-byte rule |
| **5** | **Run worker** | `RunWorker` + `runs` table; 202 + run_id; `multitask`; boot-time re-submit of orphans; `RunControl` on SIGTERM | **M** | medium |
| **6** | Perf polish | `CachePolicy` with custom `key_func`; `TimeoutPolicy`; tuned `retry_on`; `get_stream_writer()` | **S** | low |
| **7** | Observability | OTel + Langfuse; Prometheus `/metrics` | **S** | none |
| **8** | Multi-tenancy | `tenant_id` everywhere; thread prefix; `owned_case`; RLS on own tables; migration for existing threads | **L** | **high — one deliberate pass, not incremental** |
| **9** | Pack topology | `gate_mode`/`stages`/`check_predicates`; `assemble()`; conformance per gate mode; build `loan-intake` as proof | **L** | medium |

**Deferrable at no cost:** `Store` API, `Send` intra-check fan-out, `defer=True`, Redis,
distributed queue.

**Do not defer phases 1 and 5.** The parked finding that the sync-invoke window is *"effectively
unexercisable today"* **expires the moment Pipecat or Groq lands** — which is the next thing on
the roadmap.

**Critical path if you only do three things:** Phase 1 (async), Phase 3 (Postgres index),
Phase 5 (run worker). Those take VoxGate from "demo that survives a restart" to "service that
survives production", and none require the graph restructure.

---

## Bottom line

**Free and MIT, and enough:** the graph library, both Postgres checkpointer and store,
interrupts, `Command`, subgraphs, `Send`, durability modes, caching, retries, timeouts,
streaming.

**Paid and proprietary** (Elastic-2.0, closed-source, phones home, Enterprise license for
production self-host): the entire server runtime.

For a multi-tenant compliance platform the license alone settles it. Build the ~700 lines of
queue/index/SSE yourself and stay MIT top to bottom. That is also a better story in the demo
than a vendor bill.
