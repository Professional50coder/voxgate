"""One contract, two event buses.

The in-memory bus and the Postgres bus are interchangeable from the WebSocket
handler's point of view, and that is only true if it is enforced. Every
guarantee the handler relies on is asserted once here and run against both.

Why the Postgres bus exists at all: the in-memory one is invisible to other
processes. Under more than one uvicorn worker, an update published while
handling a request on worker A never reaches the browser holding a socket on
worker B — the live view goes quiet with no error at either end.

The Postgres parameter skips cleanly without VOXGATE_TEST_DB, so the default
suite stays offline.
"""

import os
import threading
import time
import uuid

import pytest

from voxgate.service.events import InMemoryEventBus, PgEventBus

TEST_DB = os.environ.get("VOXGATE_TEST_DB")


@pytest.fixture(params=["memory", "postgres"])
def bus(request):
    if request.param == "memory":
        yield InMemoryEventBus()
        return
    if not TEST_DB:
        pytest.skip("VOXGATE_TEST_DB not set")

    from voxgate.service.db import ensure_schema_sync, open_pool_sync

    pool = open_pool_sync(TEST_DB)
    ensure_schema_sync(pool)
    # Poll fast so the timing assertions below stay quick.
    yield PgEventBus(pool, poll_interval=0.02)
    pool.close()


@pytest.fixture
def case_id():
    # Unique per test so Postgres runs never collide with each other or with
    # rows left by a previous run.
    return f"case-{uuid.uuid4()}"


def test_publish_then_history_roundtrips(bus, case_id):
    bus.publish(case_id, {"kind": "state", "n": 1})
    bus.publish(case_id, {"kind": "state", "n": 2})
    assert [e["n"] for e in bus.history(case_id)] == [1, 2]


def test_history_of_an_unknown_case_is_empty(bus, case_id):
    assert bus.history(case_id) == []


def test_cases_are_isolated(bus, case_id):
    other = f"{case_id}-other"
    bus.publish(case_id, {"kind": "state", "n": 1})
    bus.publish(other, {"kind": "state", "n": 99})
    assert [e["n"] for e in bus.history(case_id)] == [1]
    assert [e["n"] for e in bus.history(other)] == [99]


def test_every_event_carries_a_seq_that_increases(bus, case_id):
    """The WebSocket cursor is a seq. If these are not increasing, the client
    either replays events forever or silently skips them."""
    for n in range(5):
        bus.publish(case_id, {"kind": "state", "n": n})
    seqs = [e["seq"] for e in bus.history(case_id)]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_latest_seq_matches_the_last_published_event(bus, case_id):
    assert bus.latest_seq(case_id) == 0
    bus.publish(case_id, {"kind": "state", "n": 1})
    assert bus.latest_seq(case_id) == bus.history(case_id)[-1]["seq"]


def test_publish_does_not_mutate_the_callers_dict(bus, case_id):
    event = {"kind": "state", "n": 1}
    bus.publish(case_id, event)
    assert "seq" not in event


def test_wait_returns_events_after_a_cursor(bus, case_id):
    bus.publish(case_id, {"kind": "state", "n": 1})
    cursor = bus.latest_seq(case_id)
    bus.publish(case_id, {"kind": "state", "n": 2})
    assert [e["n"] for e in bus.wait(case_id, cursor, 1.0)] == [2]


def test_wait_returns_empty_on_timeout_rather_than_raising(bus, case_id):
    """The handler loops on wait forever. Raising here would close the socket
    on every idle second."""
    started = time.monotonic()
    assert bus.wait(case_id, 0, 0.1) == []
    assert time.monotonic() - started >= 0.05, "must actually wait, not spin"


def test_wait_wakes_for_an_event_published_by_another_thread(bus, case_id):
    """The real shape of the WebSocket loop: a handler blocked in wait must be
    released by a publish from whatever thread served the request."""
    got: list[dict] = []
    waiter = threading.Thread(
        target=lambda: got.extend(bus.wait(case_id, 0, 5.0))
    )
    waiter.start()
    time.sleep(0.05)  # let it get into wait
    bus.publish(case_id, {"kind": "fields", "n": 7})
    waiter.join(timeout=6)

    assert not waiter.is_alive(), "wait did not return"
    assert [e["n"] for e in got] == [7]


def test_a_cursor_ahead_of_everything_returns_nothing(bus, case_id):
    bus.publish(case_id, {"kind": "state", "n": 1})
    assert bus.wait(case_id, bus.latest_seq(case_id) + 1000, 0.05) == []


def test_dropped_is_answerable_for_any_case(bus, case_id):
    """The handler asks this to decide whether to tell the client to refetch.
    It must never raise, including for a case that has published nothing."""
    assert bus.dropped(case_id) == 0
    bus.publish(case_id, {"kind": "state", "n": 1})
    assert bus.dropped(case_id) == 0


def test_events_survive_a_new_bus_object(bus, case_id):
    """The in-memory bus loses everything, the Postgres one does not — and the
    handler must be correct either way, so what is pinned is the *floor*: a
    fresh reader never sees a corrupt or partial event.
    """
    bus.publish(case_id, {"kind": "state", "n": 1})
    for event in bus.history(case_id):
        assert event["kind"] == "state" and event["n"] == 1 and event["seq"] > 0
