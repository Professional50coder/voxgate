"""Per-case event stream.

Two implementations behind one contract (`tests/contracts/test_event_bus.py`):

  InMemoryEventBus  one process, no database. Dev and tests.
  PgEventBus        durable and cross-process. Required for more than one worker.

The distinction is not cosmetic. The in-memory bus is invisible to other
processes, so under `--workers 2` a live case update published by worker A never
reaches the browser holding a WebSocket on worker B. The stream simply goes
quiet, with no error on either side. Running more than one worker therefore
requires a database; `create_app` wires this automatically and refuses to
pretend otherwise.

`EventBus` remains an alias for the in-memory implementation so existing
callers and tests keep working.

Bounded on purpose. The original implementation appended to a per-case list
that was never trimmed and whose case entries were never removed, so a
long-running process grew without limit in two directions at once: events per
case, and cases per process. On a server that stays up for weeks that is a slow
leak with no upper bound and no symptom until it matters.

Two limits, both chosen so the UI's behaviour is unaffected:

  MAX_EVENTS_PER_CASE  the client replays from an index, and a reconnecting
                       client that has fallen more than this far behind is
                       better served by refetching the case than by replaying
                       thousands of stale events.
  MAX_CASES            an LRU bound. Evicting the least recently touched case
                       loses only its event history, never the case itself:
                       the case lives in the store and the checkpointer.

Neither limit can lose data that is not recoverable from the store.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict, deque
from typing import Protocol, runtime_checkable

MAX_EVENTS_PER_CASE = 500
MAX_CASES = 2_000


@runtime_checkable
class EventStream(Protocol):
    def publish(self, case_id: str, event: dict) -> None: ...
    def history(self, case_id: str) -> list[dict]: ...
    def latest_seq(self, case_id: str) -> int: ...
    def dropped(self, case_id: str) -> int: ...
    def wait(self, case_id: str, after_seq: int, timeout: float) -> list[dict]: ...


class InMemoryEventBus:
    def __init__(
        self,
        max_events_per_case: int = MAX_EVENTS_PER_CASE,
        max_cases: int = MAX_CASES,
    ) -> None:
        self._cond = threading.Condition()
        # OrderedDict as an LRU: move_to_end on touch, popitem(last=False) to
        # evict the coldest case.
        self._events: OrderedDict[str, deque[dict]] = OrderedDict()
        self._dropped: dict[str, int] = {}
        self._max_events = max_events_per_case
        self._max_cases = max_cases
        # Monotonic per case. A positional cursor is wrong as soon as the ring
        # buffer evicts: the client's index stops meaning what it meant, and
        # `len(queue) > after_index` silently goes permanently false, killing
        # the stream with no error. Sequence numbers survive eviction.
        self._next_seq: dict[str, int] = {}

    def publish(self, case_id: str, event: dict) -> None:
        with self._cond:
            queue = self._events.get(case_id)
            if queue is None:
                queue = deque(maxlen=self._max_events)
                self._events[case_id] = queue
                while len(self._events) > self._max_cases:
                    evicted, _ = self._events.popitem(last=False)
                    self._dropped.pop(evicted, None)
            else:
                self._events.move_to_end(case_id)

            # deque(maxlen) silently discards the oldest. Count it, so `wait`
            # can tell a caller its cursor is stale rather than quietly
            # returning the wrong slice.
            if len(queue) == self._max_events:
                self._dropped[case_id] = self._dropped.get(case_id, 0) + 1

            seq = self._next_seq.get(case_id, 0) + 1
            self._next_seq[case_id] = seq
            # Stamped on a copy so a caller's dict is never mutated underneath
            # them, and so re-publishing the same object cannot corrupt history.
            queue.append({**event, "seq": seq})
            self._cond.notify_all()

    def history(self, case_id: str) -> list[dict]:
        with self._cond:
            queue = self._events.get(case_id)
            return list(queue) if queue else []

    def dropped(self, case_id: str) -> int:
        """How many events were evicted for this case.

        A client whose cursor predates the retained window can use this to
        decide to refetch rather than assume it has the full history.
        """
        with self._cond:
            return self._dropped.get(case_id, 0)

    def latest_seq(self, case_id: str) -> int:
        with self._cond:
            return self._next_seq.get(case_id, 0)

    def wait(self, case_id: str, after_seq: int, timeout: float) -> list[dict]:
        """Events newer than `after_seq`, blocking up to `timeout`.

        Filters on sequence number, not list position. A client that falls
        behind the retained window gets whatever is still retained rather than
        an empty slice forever, and `dropped()` tells it history was lost.
        """
        with self._cond:
            self._cond.wait_for(
                lambda: self._next_seq.get(case_id, 0) > after_seq,
                timeout=timeout,
            )
            queue = self._events.get(case_id)
            if not queue:
                return []
            return [e for e in queue if e.get("seq", 0) > after_seq]


# The in-memory bus is the historical name. Kept so callers that never needed a
# choice do not have to make one.
EventBus = InMemoryEventBus


class PgEventBus:
    """Durable, cross-process event stream backed by the `events` table.

    This is what makes more than one worker safe. With the in-memory bus, a
    browser holding a WebSocket on worker B never sees an update published by
    worker A: the stream goes quiet with no error anywhere. Both workers read
    and write the same table here, so it does not matter which one served which
    request.

    **Polling, not LISTEN/NOTIFY.** LISTEN needs a session that stays pinned to
    one backend for the life of the subscription, which is exactly what a
    transaction-pooling proxy does not give you — and the pool is deliberately
    configured for pgbouncer and Neon's pooled endpoint (`prepare_threshold=0`,
    `autocommit=True`). A LISTEN-based bus would work on a direct connection and
    silently deliver nothing through the pooler that production actually uses.
    Polling a `seq > cursor` index is slightly less elegant and always correct.

    The event stream is an accelerator, never a source of truth: every event
    carries state that `GET /cases/{id}` can re-derive from the checkpointer, so
    a missed poll costs latency, not data.
    """

    # A WebSocket poll costs one indexed lookup. At 250ms the UI feels live and
    # an idle connection costs four trivial queries a second.
    POLL_INTERVAL = 0.25

    def __init__(self, pool, tenant_id: str = "default",
                 retain: int = MAX_EVENTS_PER_CASE,
                 poll_interval: float = POLL_INTERVAL) -> None:
        self._pool = pool
        self._tenant = tenant_id
        self._retain = retain
        self._poll = poll_interval

    def publish(self, case_id: str, event: dict) -> None:
        """Append an event, allocating a per-case seq that is safe to poll.

        A global `bigserial` is not merely suboptimal here, it is wrong: a
        sequence hands out its value BEFORE the transaction commits, so rows can
        become visible out of seq order. A cursor-based poller that reads seq=11
        advances past it, and the seq=10 committing a moment later is never
        asked for again. Measured before this changed: ~1.2% of events present
        in the table and silently never delivered to a live viewer.

        So the counter is bumped and the event inserted in **one transaction**.
        The `ON CONFLICT DO UPDATE` takes an exclusive row lock on that case's
        counter row and holds it until commit, so the next writer for this case
        cannot obtain a seq until this event is committed and visible. A visible
        seq therefore implies every lower seq for the case is visible — exactly
        the guarantee `wait` needs before it is allowed to advance a cursor.

        Writers for one case block each other for the length of one insert.
        Writers for different cases touch different rows and never interact.
        """
        payload = json.dumps(event, default=str)   # default=str: payloads carry datetimes
        kind = str(event.get("kind", "state"))
        with self._pool.connection() as conn:
            # Explicit transaction: the pool runs autocommit, which would commit
            # the counter bump on its own and release the lock before the event
            # existed — reintroducing the exact gap this is here to close.
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO event_seq (tenant_id, case_id, next_seq)
                    VALUES (%s, %s, 1)
                    ON CONFLICT (tenant_id, case_id)
                    DO UPDATE SET next_seq = event_seq.next_seq + 1
                    RETURNING next_seq
                    """,
                    (self._tenant, case_id),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO events (tenant_id, case_id, seq, kind, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (self._tenant, case_id, row["next_seq"], kind, payload),
                )

    @staticmethod
    def _to_event(row: dict) -> dict:
        return {**(row["payload"] or {}), "seq": row["seq"]}

    def history(self, case_id: str) -> list[dict]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT seq, payload FROM events
                WHERE tenant_id = %s AND case_id = %s
                ORDER BY seq DESC LIMIT %s
                """,
                (self._tenant, case_id, self._retain),
            ).fetchall()
        return [self._to_event(r) for r in reversed(rows)]

    def latest_seq(self, case_id: str) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM events "
                "WHERE tenant_id = %s AND case_id = %s",
                (self._tenant, case_id),
            ).fetchone()
        return int(row["seq"])

    def dropped(self, case_id: str) -> int:
        """Always zero: nothing is evicted, so no client can be behind a window.

        Part of the contract because the in-memory bus can drop and the
        WebSocket handler must not care which bus it is talking to.
        """
        return 0

    def _since(self, case_id: str, after_seq: int) -> list[dict]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT seq, payload FROM events
                WHERE tenant_id = %s AND case_id = %s AND seq > %s
                ORDER BY seq LIMIT %s
                """,
                (self._tenant, case_id, after_seq, self._retain),
            ).fetchall()
        return [self._to_event(r) for r in rows]

    def wait(self, case_id: str, after_seq: int, timeout: float) -> list[dict]:
        """Events newer than `after_seq`, polling until `timeout`.

        Returns as soon as anything is available, so the common case costs one
        query and no sleep. Called from a thread (`asyncio.to_thread`), so
        blocking here does not stall the event loop.
        """
        deadline = time.monotonic() + timeout
        while True:
            found = self._since(case_id, after_seq)
            if found:
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            time.sleep(min(self._poll, remaining))
