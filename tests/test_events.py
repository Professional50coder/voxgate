"""EventBus bounds.

The bus is in-process and long-lived, so anything unbounded in it is a leak
that only shows up after a server has been up for weeks. These tests pin the
two limits and, more importantly, pin that hitting a limit degrades safely
rather than corrupting a client's view.
"""

from voxgate.service.events import EventBus


def test_publish_then_history_roundtrips():
    bus = EventBus()
    bus.publish("c1", {"kind": "state", "n": 1})
    bus.publish("c1", {"kind": "state", "n": 2})
    assert [e["n"] for e in bus.history("c1")] == [1, 2]


def test_cases_are_isolated():
    bus = EventBus()
    bus.publish("c1", {"n": 1})
    bus.publish("c2", {"n": 99})
    assert [e["n"] for e in bus.history("c1")] == [1]


def test_unknown_case_has_empty_history():
    assert EventBus().history("nope") == []


def test_events_per_case_are_bounded():
    """Without this the list grows for the life of the process."""
    bus = EventBus(max_events_per_case=5)
    for i in range(20):
        bus.publish("c1", {"n": i})
    history = bus.history("c1")
    assert len(history) == 5
    # The newest are kept, because a live view cares about recent state.
    assert [e["n"] for e in history] == [15, 16, 17, 18, 19]


def test_dropped_events_are_counted_not_hidden():
    """A client whose cursor predates the window needs to know to refetch."""
    bus = EventBus(max_events_per_case=3)
    for i in range(10):
        bus.publish("c1", {"n": i})
    assert bus.dropped("c1") == 7
    assert bus.dropped("never-seen") == 0


def test_case_count_is_bounded_by_lru():
    """Cases were never removed, so a busy server leaked one entry per case
    forever."""
    bus = EventBus(max_cases=3)
    for i in range(6):
        bus.publish(f"case-{i}", {"n": i})
    retained = [c for c in range(6) if bus.history(f"case-{c}")]
    assert len(retained) == 3
    assert retained == [3, 4, 5], "the coldest cases should be evicted"


def test_touching_a_case_keeps_it_from_eviction():
    bus = EventBus(max_cases=2)
    bus.publish("old", {"n": 1})
    bus.publish("new", {"n": 2})
    bus.publish("old", {"n": 3})       # touch: 'old' becomes most recent
    bus.publish("newest", {"n": 4})    # evicts the coldest, which is 'new'
    assert bus.history("old")
    assert bus.history("newest")
    assert bus.history("new") == []


def test_events_are_stamped_with_a_monotonic_seq():
    bus = EventBus()
    bus.publish("c1", {"n": 1})
    bus.publish("c1", {"n": 2})
    assert [e["seq"] for e in bus.history("c1")] == [1, 2]


def test_publish_does_not_mutate_the_callers_dict():
    bus = EventBus()
    event = {"n": 1}
    bus.publish("c1", event)
    assert "seq" not in event


def test_wait_returns_events_after_a_seq():
    bus = EventBus()
    bus.publish("c1", {"n": 1})
    bus.publish("c1", {"n": 2})
    assert [e["n"] for e in bus.wait("c1", after_seq=1, timeout=0.1)] == [2]


def test_wait_times_out_cleanly_with_no_events():
    assert EventBus().wait("c1", after_seq=0, timeout=0.01) == []


def test_stream_survives_eviction():
    """Regression, and the sharpest one here.

    With a positional cursor, once the client's index reached the ring buffer's
    maxlen, `len(queue) > after_index` was never true again: the stream died
    silently, with no error and no reconnect. Sequence numbers survive
    eviction, so a client that falls behind still receives new events.
    """
    bus = EventBus(max_events_per_case=5)
    for i in range(12):
        bus.publish("c1", {"n": i})

    cursor, delivered = 0, []
    for _ in range(3):
        for e in bus.wait("c1", cursor, 0.01):
            delivered.append(e["n"])
            cursor = max(cursor, e["seq"])

    assert delivered == [7, 8, 9, 10, 11], "should receive the retained window"

    bus.publish("c1", {"n": 99})
    assert [e["n"] for e in bus.wait("c1", cursor, 0.05)] == [99], (
        "a new event must still arrive after the cursor passed maxlen"
    )
    assert bus.dropped("c1") == 8, "and the client can tell history was lost"


def test_a_cursor_ahead_of_everything_returns_nothing_and_does_not_raise():
    bus = EventBus(max_events_per_case=3)
    for i in range(10):
        bus.publish("c1", {"n": i})
    assert bus.wait("c1", after_seq=9999, timeout=0.01) == []
