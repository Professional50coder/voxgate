"""One contract, two implementations.

The only real objection to having both an in-memory and a Postgres store is
silent divergence. This suite is the answer: every behavioural guarantee is
asserted once and run against both, so an implementation that drifts fails.

The Postgres parameter skips cleanly without VOXGATE_TEST_DB, keeping the
default suite offline.
"""

import os
import uuid

import pytest

from voxgate.service.store import InMemoryCaseStore, PgCaseStore

TEST_DB = os.environ.get("VOXGATE_TEST_DB")


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        yield InMemoryCaseStore()
        return
    if not TEST_DB:
        pytest.skip("VOXGATE_TEST_DB not set")

    from voxgate.service.db import ensure_schema_sync, open_pool_sync

    pool = open_pool_sync(TEST_DB)
    ensure_schema_sync(pool)
    yield PgCaseStore(pool)
    pool.close()


@pytest.fixture
def tenant():
    # Unique per test so Postgres runs never collide with each other or with
    # leftovers from a previous run.
    return f"t-{uuid.uuid4().hex[:10]}"


def case(case_id="c1", **overrides):
    base = {"case_id": case_id, "pack_id": "kyc-uae", "status": "processing"}
    base.update(overrides)
    return base


def test_upsert_then_get_roundtrips(store, tenant):
    store.upsert(tenant, case())
    got = store.get(tenant, "c1")
    assert got["case_id"] == "c1"
    assert got["status"] == "processing"
    assert got["pack_id"] == "kyc-uae"


def test_get_unknown_case_is_none(store, tenant):
    assert store.get(tenant, "nope") is None


def test_upsert_merges_rather_than_replaces(store, tenant):
    """patch_fields sends only live_fields. If upsert replaced, it would wipe
    the score and audit trail written by the previous sync."""
    store.upsert(tenant, case(score={"band": "low"}, audit=[{"seq": 1}]))
    store.upsert(tenant, {"case_id": "c1", "live_fields": {"full_name": "Priya"}})
    got = store.get(tenant, "c1")
    assert got["live_fields"] == {"full_name": "Priya"}
    assert got["score"] == {"band": "low"}, "unspecified keys must survive"
    assert got["audit"] == [{"seq": 1}]
    assert got["pack_id"] == "kyc-uae"


def test_status_updates_are_visible(store, tenant):
    store.upsert(tenant, case())
    store.upsert(tenant, {"case_id": "c1", "status": "approved"})
    assert store.get(tenant, "c1")["status"] == "approved"


def test_nested_payload_survives_a_roundtrip(store, tenant):
    """Postgres stores this as jsonb; the in-memory store keeps Python objects.
    Both must return the same shape."""
    payload = {
        "fields": {"full_name": "Priya Raghavan", "dob": "1992-04-15"},
        "score": {"probability": 0.1234, "band": "low",
                  "contributions": [{"feature": "x", "contribution": -0.5}]},
        "check_results": [{"check_name": "sanctions", "status": "clear"}],
        "interrupt": None,
    }
    store.upsert(tenant, case(**payload))
    got = store.get(tenant, "c1")
    for key, value in payload.items():
        assert got[key] == value, key


def test_tenants_are_isolated(store, tenant):
    other = f"{tenant}-other"
    store.upsert(tenant, case())
    assert store.get(other, "c1") is None
    assert store.list(other) == []


def test_list_filters_by_pack(store, tenant):
    store.upsert(tenant, case("c1", pack_id="kyc-uae"))
    store.upsert(tenant, case("c2", pack_id="loan-intake"))
    got = store.list(tenant, pack_id="loan-intake")
    assert [c["case_id"] for c in got] == ["c2"]


def test_list_is_newest_first(store, tenant):
    store.upsert(tenant, case("c1"))
    store.upsert(tenant, case("c2"))
    store.upsert(tenant, case("c3"))
    assert [c["case_id"] for c in store.list(tenant)] == ["c3", "c2", "c1"]


def test_updating_a_case_does_not_reorder_it(store, tenant):
    """seq is assigned on insert, not on update: a reviewer's queue should not
    reshuffle every time a case ticks forward."""
    store.upsert(tenant, case("c1"))
    store.upsert(tenant, case("c2"))
    store.upsert(tenant, {"case_id": "c1", "status": "approved"})
    assert [c["case_id"] for c in store.list(tenant)] == ["c2", "c1"]


def test_mutating_a_returned_case_does_not_corrupt_the_store(store, tenant):
    """Regression. The original store returned live internal references, so a
    caller mutating a returned case silently corrupted state."""
    store.upsert(tenant, case())
    got = store.get(tenant, "c1")
    got["status"] = "TAMPERED"
    got.setdefault("fields", {})["injected"] = True
    assert store.get(tenant, "c1")["status"] == "processing"


def test_listed_cases_are_copies_too(store, tenant):
    store.upsert(tenant, case())
    listed = store.list(tenant)
    listed[0]["status"] = "TAMPERED"
    assert store.get(tenant, "c1")["status"] == "processing"


# --------------------------------------------------------------------------
# The whole point of the Postgres implementation
# --------------------------------------------------------------------------

@pytest.mark.skipif(not TEST_DB, reason="VOXGATE_TEST_DB not set")
def test_cases_survive_a_new_store_instance():
    """A new PgCaseStore is what a process restart looks like to the data.

    This is the failure the whole exercise exists to fix: the board read 3
    cases, then 1, purely because the backend restarted.
    """
    from voxgate.service.db import ensure_schema_sync, open_pool_sync

    tenant = f"t-{uuid.uuid4().hex[:10]}"

    pool = open_pool_sync(TEST_DB)
    ensure_schema_sync(pool)
    before = PgCaseStore(pool)
    before.upsert(tenant, case("survivor", status="awaiting_review",
                               score={"band": "high"}))
    pool.close()

    # Everything above is gone. New pool, new store, same database.
    pool2 = open_pool_sync(TEST_DB)
    after = PgCaseStore(pool2)
    recovered = after.get(tenant, "survivor")
    pool2.close()

    assert recovered is not None, "the case did not survive"
    assert recovered["status"] == "awaiting_review"
    assert recovered["score"] == {"band": "high"}
