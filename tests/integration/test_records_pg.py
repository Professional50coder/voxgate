"""Transcripts and the agent store against real Postgres.

Each test gets a brand-new database, migrated to head, and drops it after, so
nothing here can touch real data. Requires VOXGATE_TEST_DB; skipped otherwise.
"""
import os
import threading
import uuid

import psycopg
import pytest

from voxgate.service.db import ensure_schema_sync, open_pool_sync
from voxgate.service.records import PgPackStore, PgTranscriptStore

from tests.test_publish import spec

TEST_DB = os.environ.get("VOXGATE_TEST_DB")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="VOXGATE_TEST_DB not set")


@pytest.fixture
def pool():
    name = f"voxgate_rec_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(TEST_DB, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    base, _, rest = TEST_DB.rpartition("/")
    query = ("?" + rest.split("?", 1)[1]) if "?" in rest else ""
    dsn = f"{base}/{name}{query}"
    p = open_pool_sync(dsn, min_size=1, max_size=8)
    ensure_schema_sync(p)
    try:
        yield p
    finally:
        p.close()
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                      "WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.close()


def test_turns_are_numbered_and_summaries_persist(pool):
    ts = PgTranscriptStore(pool)
    assert ts.append("t", "c1", "s1", [{"role": "agent", "text": "Your name?"},
                                      {"role": "applicant", "text": "Fatima"}]) == 2
    assert ts.append("t", "c1", "s1", [{"role": "agent", "text": "Thanks."}]) == 3
    ts.finish("t", "c1", "s1", {"narrative": "ok", "duration_ms": 9000})
    loaded = ts.load("t", "c1", "s1")
    assert [e["turn_no"] for e in loaded["entries"]] == [0, 1, 2]
    assert loaded["summary"]["narrative"] == "ok"
    [row] = ts.sessions("t", "c1")
    assert row["turns"] == 3 and row["finished_at"]


def test_concurrent_appends_never_share_a_turn_number(pool):
    ts = PgTranscriptStore(pool)
    threads = [threading.Thread(target=ts.append, args=(
        "t", "c2", "s1", [{"role": "applicant", "text": f"line {i}"}])) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [e["turn_no"] for e in ts.load("t", "c2", "s1")["entries"]] == list(range(8))


def test_full_text_search_is_ranked_and_tenant_scoped(pool):
    ts = PgTranscriptStore(pool)
    ts.append("t", "c3", "s1", [{"role": "applicant", "text": "my brother handles the source of funds"}])
    ts.append("other", "c4", "s1", [{"role": "applicant", "text": "source of funds is salary"}])
    hits = ts.search("t", "source funds")
    assert [h["case_id"] for h in hits] == ["c3"]


def test_published_specs_are_shared_between_instances(pool):
    a, b = PgPackStore(pool), PgPackStore(pool)
    a.save("t", spec(), "priya")
    assert [s["pack_id"] for s in b.specs("t")] == ["test-clinic"]
    a.save("t", spec(display_name="Renamed"), "omar")
    [row] = b.listing("t")
    assert row["display_name"] == "Renamed" and row["created_by"] == "omar"
