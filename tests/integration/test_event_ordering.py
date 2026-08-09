"""Concurrent publishers must not make a live viewer miss an event.

This is the subtlest bug the event stream has had, and it was self-inflicted.

`events.seq` started as a global `bigserial`. A sequence hands out its value
BEFORE the transaction commits, so writer A can take seq=10, writer B take
seq=11 and commit first. A poller reading at that instant sees 11, advances its
cursor past it, and never asks for anything <= 11 again — so A's event is lost
the moment it commits. Every row is in the table; the viewer just never receives
some of them. Measured at ~1.2% loss with eight concurrent writers.

Nothing about that failure is visible from a single-threaded test, which is why
the contract suite passed throughout. It needs real concurrency against real
Postgres. Requires VOXGATE_TEST_DB; skipped otherwise.
"""

import os
import threading
import time
import uuid

import pytest

from voxgate.service.events import PgEventBus

TEST_DB = os.environ.get("VOXGATE_TEST_DB")

pytestmark = pytest.mark.skipif(not TEST_DB, reason="VOXGATE_TEST_DB not set")

WRITERS = 8
PER_WRITER = 25
TOTAL = WRITERS * PER_WRITER


@pytest.fixture
def pool():
    from voxgate.service.db import ensure_schema_sync, open_pool_sync

    p = open_pool_sync(TEST_DB, min_size=4, max_size=20)
    ensure_schema_sync(p)
    yield p
    p.close()


def test_a_poller_receives_every_event_under_concurrent_writers(pool):
    """The regression. A poller advancing a cursor must never skip a commit."""
    case_id = f"case-{uuid.uuid4()}"
    bus = PgEventBus(pool, poll_interval=0.005)
    seen: set[int] = set()
    errors: list[Exception] = []
    stop = threading.Event()

    def poll():
        cursor = 0
        while not stop.is_set():
            for event in bus.wait(case_id, cursor, 0.05):
                seen.add(event["n"])
                cursor = max(cursor, event["seq"])

    def write(w):
        for i in range(PER_WRITER):
            try:
                bus.publish(case_id, {"kind": "state", "n": w * PER_WRITER + i})
            except Exception as exc:                      # noqa: BLE001 - asserted below
                errors.append(exc)

    poller = threading.Thread(target=poll)
    poller.start()
    writers = [threading.Thread(target=write, args=(w,)) for w in range(WRITERS)]
    for t in writers:
        t.start()
    for t in writers:
        t.join(timeout=60)

    time.sleep(2.0)          # let the poller drain what is left
    stop.set()
    poller.join(timeout=10)

    assert not errors, f"publish raised: {errors[0]!r}"
    missing = sorted(set(range(TOTAL)) - seen)
    assert not missing, (
        f"{len(missing)} of {TOTAL} events were committed but never delivered: "
        f"{missing[:10]}"
    )


def test_per_case_seq_is_gapless_under_concurrent_writers(pool):
    """Why the delivery guarantee holds, stated as an invariant.

    Seq N+1 can only be allocated after N is committed, so a gap would mean a
    writer obtained a seq without the previous event being visible — the exact
    condition that lets a poller skip one.
    """
    case_id = f"case-{uuid.uuid4()}"
    bus = PgEventBus(pool)

    writers = [
        threading.Thread(target=lambda w=w: [
            bus.publish(case_id, {"kind": "state", "n": w * 10 + i}) for i in range(10)
        ])
        for w in range(6)
    ]
    for t in writers:
        t.start()
    for t in writers:
        t.join(timeout=60)

    seqs = [e["seq"] for e in bus.history(case_id)]
    assert seqs == list(range(1, 61)), f"expected a gapless 1..60, got {seqs}"


def test_cases_do_not_block_each_other(pool):
    """Allocation locks one counter row per case. If it were a global lock,
    every publish in the system would queue behind every other one."""
    bus = PgEventBus(pool)
    prefix = uuid.uuid4()

    started = time.monotonic()
    threads = [
        threading.Thread(target=lambda n=n: [
            bus.publish(f"case-{prefix}-{n}", {"kind": "state", "n": i}) for i in range(20)
        ])
        for n in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    elapsed = time.monotonic() - started

    assert not [t for t in threads if t.is_alive()]
    assert elapsed < 10.0, f"120 publishes across 6 cases took {elapsed:.1f}s"
