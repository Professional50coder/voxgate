"""The shared quota, against real Postgres.

The property that matters is the one the in-process limiter cannot have: two
workers counting against the same total. Every test here builds two independent
`PgQuota` objects — which is what two worker processes are — and asserts they
agree.

Requires VOXGATE_TEST_DB; skipped otherwise.
"""

import os
import threading
import uuid

import pytest

from voxgate.service.quota import PgQuota, subject_for

TEST_DB = os.environ.get("VOXGATE_TEST_DB")

pytestmark = pytest.mark.skipif(not TEST_DB, reason="VOXGATE_TEST_DB not set")


@pytest.fixture
def pool():
    from voxgate.service.db import ensure_schema_sync, open_pool_sync

    p = open_pool_sync(TEST_DB, min_size=2, max_size=12)
    ensure_schema_sync(p)
    yield p
    p.close()


@pytest.fixture
def subject():
    return f"key:test-{uuid.uuid4().hex}"


def test_a_request_is_counted(pool, subject):
    quota = PgQuota(pool, limit=5)
    first = quota.check_and_count(subject, "/packs/draft")
    assert first.allowed
    assert first.used == 1
    assert first.remaining == 4


def test_the_limit_is_a_ceiling_on_successful_requests(pool, subject):
    """The caller that pushes the count past the limit is the one refused, not
    the one that reaches it — a limit of 5 must allow five."""
    quota = PgQuota(pool, limit=5)
    allowed = [quota.check_and_count(subject, "/packs/draft").allowed for _ in range(6)]
    assert allowed == [True, True, True, True, True, False]


def test_two_workers_share_one_total(pool, subject):
    """The whole reason this exists.

    The in-process limiter gives each worker its own count, so N workers means N
    times the ceiling. These two objects are two worker processes.
    """
    worker_a = PgQuota(pool, limit=4)
    worker_b = PgQuota(pool, limit=4)

    assert worker_a.check_and_count(subject, "/packs/draft").allowed
    assert worker_b.check_and_count(subject, "/packs/draft").allowed
    assert worker_a.check_and_count(subject, "/packs/draft").allowed
    assert worker_b.check_and_count(subject, "/packs/draft").allowed

    refused = worker_a.check_and_count(subject, "/packs/draft")
    assert not refused.allowed, "each worker counted its own share"
    assert refused.used == 5


def test_concurrent_requests_do_not_overshoot(pool, subject):
    """Read-then-write would let several workers each see "one under" and all
    allow. The count and the check are one statement for this reason."""
    quota_objects = [PgQuota(pool, limit=20) for _ in range(6)]
    results: list[bool] = []
    guard = threading.Lock()

    def spend(q):
        for _ in range(10):
            decision = q.check_and_count(subject, "/packs/draft")
            with guard:
                results.append(decision.allowed)

    threads = [threading.Thread(target=spend, args=(q,)) for q in quota_objects]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not [t for t in threads if t.is_alive()]
    assert len(results) == 60
    assert sum(results) == 20, f"allowed {sum(results)} of a 20 limit"


def test_endpoints_are_counted_separately(pool, subject):
    """Exhausting drafting must not lock an operator out of publishing."""
    quota = PgQuota(pool, limit=2)
    for _ in range(3):
        quota.check_and_count(subject, "/packs/draft")

    assert not quota.check_and_count(subject, "/packs/draft").allowed
    assert quota.check_and_count(subject, "/packs/publish").allowed


def test_subjects_are_isolated(pool):
    quota = PgQuota(pool, limit=1)
    a, b = f"key:{uuid.uuid4().hex}", f"key:{uuid.uuid4().hex}"

    assert quota.check_and_count(a, "/packs/draft").allowed
    assert not quota.check_and_count(a, "/packs/draft").allowed
    assert quota.check_and_count(b, "/packs/draft").allowed, "b paid for a's usage"


def test_a_new_window_resets_the_count(pool, subject):
    """Fixed windows, so a one-second window is a complete test of the reset."""
    import time

    quota = PgQuota(pool, limit=1, window_seconds=1)
    assert quota.check_and_count(subject, "/packs/draft").allowed
    assert not quota.check_and_count(subject, "/packs/draft").allowed

    time.sleep(1.2)
    assert quota.check_and_count(subject, "/packs/draft").allowed


def test_usage_is_reportable(pool, subject):
    """An operator needs to see where the budget went, not only that it ran
    out."""
    quota = PgQuota(pool, limit=50)
    for _ in range(3):
        quota.check_and_count(subject, "/packs/draft")
    quota.check_and_count(subject, "/packs/publish")

    assert quota.usage(subject) == {"/packs/draft": 3, "/packs/publish": 1}


def test_closed_windows_are_purged(pool):
    """Without this the table grows one row per subject per window forever."""
    import time

    subject = f"key:{uuid.uuid4().hex}"
    quota = PgQuota(pool, limit=10, window_seconds=1)
    quota.check_and_count(subject, "/packs/draft")
    assert quota.usage(subject)

    time.sleep(1.2)
    assert quota.purge_expired() >= 1
    assert quota.usage(subject) == {}


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

def test_the_key_is_hashed_not_stored():
    """This table is readable by anyone with database access and lands in
    slow-query logs. A quota counter is not a reason for a credential to exist
    in either."""
    key = "super-secret-operator-key"
    subject = subject_for(key, "10.0.0.1")

    assert key not in subject
    assert subject.startswith("key:")
    assert subject_for(key, "10.0.0.2") == subject, "must follow the key, not the IP"


def test_without_a_key_the_address_is_the_subject():
    """Keeps the applicant surface metered, without pretending an IP means more
    than it does."""
    assert subject_for(None, "10.0.0.1") == "addr:10.0.0.1"
    assert subject_for("", "10.0.0.1") == "addr:10.0.0.1"


def test_a_broken_counter_fails_open(subject):
    """A cost control, not an authorization check. Refusing every request
    because the counter is unreachable turns a metering outage into a service
    outage — and the in-process burst limiter is still in front of it."""
    class Broken:
        def connection(self):
            raise RuntimeError("pool is down")

    decision = PgQuota(Broken(), limit=1).check_and_count(subject, "/packs/draft")
    assert decision.allowed
