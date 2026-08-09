"""Per-case serialisation, and the deadlock it nearly introduced.

Two resumes racing the same interrupt both read the same checkpoint, both
invoke, and the second overwrites the first — a double-clicked review form
silently discarding a decision. `CaseRunner._case_lock` serialises them.

The second test here exists because the first version of that lock was worse
than the bug: it took its Postgres connection from the store's pool and held it
for the whole graph invocation, while the work under it needed a second
connection from the same pool. Five concurrent resumes against a five-connection
pool deadlocked outright. A dedicated lock pool fixes it; this pins it.

Requires VOXGATE_TEST_DB; skipped otherwise.
"""

import os
import threading
import time
import uuid

import pytest

TEST_DB = os.environ.get("VOXGATE_TEST_DB")

pytestmark = pytest.mark.skipif(not TEST_DB, reason="VOXGATE_TEST_DB not set")


@pytest.fixture
def pools():
    from voxgate.service.db import ensure_schema_sync, open_pool_sync

    store_pool = open_pool_sync(TEST_DB, min_size=1, max_size=5)
    ensure_schema_sync(store_pool)
    lock_pool = open_pool_sync(TEST_DB, min_size=0, max_size=10)
    yield store_pool, lock_pool
    store_pool.close()
    lock_pool.close()


def _runner(store_pool, lock_pool):
    from langgraph.checkpoint.memory import MemorySaver

    from voxgate.service.events import InMemoryEventBus
    from voxgate.service.runner import CaseRunner
    from voxgate.service.store import PgCaseStore

    return CaseRunner({}, MemorySaver, PgCaseStore(store_pool),
                      InMemoryEventBus(), lock_pool=lock_pool)


def test_work_under_the_lock_can_still_reach_the_store(pools):
    """The deadlock regression.

    Each thread holds a lock for a different case — so the in-process locks
    never contend and every thread is inside `_case_lock` at once — and then
    does a store read, which needs a connection from the store's pool. Sharing
    one pool between the two hangs here until the pool times out.
    """
    store_pool, lock_pool = pools
    runner = _runner(store_pool, lock_pool)
    tenant = f"t-{uuid.uuid4()}"
    finished, errors = [], []

    def resume_like(n):
        try:
            with runner._case_lock(f"case-{n}"):
                time.sleep(0.2)
                runner.store.list(tenant)      # what _sync does under the lock
                finished.append(n)
        except Exception as exc:               # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=resume_like, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not [t for t in threads if t.is_alive()], "threads deadlocked"
    assert not errors, f"pool starvation: {errors[0]!r}"
    assert sorted(finished) == [0, 1, 2, 3, 4]


def test_the_same_case_is_serialised(pools):
    """Two holders of one case's lock never overlap."""
    store_pool, lock_pool = pools
    runner = _runner(store_pool, lock_pool)
    case_id = f"case-{uuid.uuid4()}"
    inside, overlaps = [], []
    guard = threading.Lock()

    def hold():
        with runner._case_lock(case_id):
            with guard:
                inside.append(1)
                if len(inside) > 1:
                    overlaps.append(len(inside))
            time.sleep(0.15)
            with guard:
                inside.pop()

    threads = [threading.Thread(target=hold) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not [t for t in threads if t.is_alive()]
    assert not overlaps, "two resumes advanced the same case at once"


def test_different_cases_are_not_serialised(pools):
    """The lock is per case, not global. A per-process global lock would make
    every resume queue behind every other one."""
    store_pool, lock_pool = pools
    runner = _runner(store_pool, lock_pool)
    prefix = uuid.uuid4()

    started = time.monotonic()
    threads = []
    for n in range(4):
        def hold(n=n):
            with runner._case_lock(f"case-{prefix}-{n}"):
                time.sleep(0.3)
        t = threading.Thread(target=hold)
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=20)
    elapsed = time.monotonic() - started

    assert not [t for t in threads if t.is_alive()]
    assert elapsed < 1.0, (
        f"four independent cases took {elapsed:.2f}s; they ran in series"
    )
