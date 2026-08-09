"""Migrations, run against a real throwaway database.

The point of replacing `CREATE TABLE IF NOT EXISTS` with Alembic is the ability
to change a schema that already has data in it. A test that only checks "the
tables exist afterwards" would pass equally well against the script that was
replaced, and would prove nothing about that ability — so the assertions here
are about the version table, about adopting a pre-existing database without
touching its rows, and about round-tripping down and back up.

Each test builds its own database and drops it, so nothing here can damage the
developer's. Requires VOXGATE_TEST_DB; skipped otherwise.
"""

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from voxgate.service.db import ensure_schema_sync, open_pool_sync

TEST_DB = os.environ.get("VOXGATE_TEST_DB")

pytestmark = pytest.mark.skipif(not TEST_DB, reason="VOXGATE_TEST_DB not set")


@pytest.fixture
def fresh_dsn():
    """A brand-new empty database, dropped afterwards."""
    name = f"voxgate_mig_{uuid.uuid4().hex[:12]}"
    admin = psycopg.connect(TEST_DB, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    dsn = TEST_DB.rsplit("/", 1)[0] + "/" + name
    try:
        yield dsn
    finally:
        # Terminate stragglers first: DROP DATABASE fails while anything is
        # still connected, and a leaked test database is worse than a slow test.
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.close()


def tables(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return {
            r["tablename"]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }


def version(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return row["version_num"]


def head_revision() -> str:
    """The latest revision, read from the scripts rather than hardcoded.

    These assertions originally named "0001" and broke the moment a second
    migration was added — which is exactly the wrong moment for the migration
    tests to fail, because the failure says nothing about whether the new
    migration works.
    """
    from alembic.script import ScriptDirectory

    from voxgate.service.db import _alembic_config

    return ScriptDirectory.from_config(_alembic_config()).get_current_head()


EXPECTED_TABLES = {"cases", "events", "event_seq", "runs", "quota_usage"}


def test_an_empty_database_is_brought_to_head(fresh_dsn):
    ensure_schema_sync(dsn=fresh_dsn)

    assert EXPECTED_TABLES <= tables(fresh_dsn)
    assert version(fresh_dsn) == head_revision()


def test_running_twice_is_a_no_op(fresh_dsn):
    """Called on every start, so this has to be true or restarts break."""
    ensure_schema_sync(dsn=fresh_dsn)
    ensure_schema_sync(dsn=fresh_dsn)
    assert version(fresh_dsn) == head_revision()


def test_it_adopts_a_database_created_before_migrations_existed(fresh_dsn):
    """The baseline's whole reason for being idempotent.

    Simulates a deployment created by the old `CREATE TABLE IF NOT EXISTS`
    script: real tables, real rows, no `alembic_version`. Adopting it must stamp
    the version and leave every row alone.
    """
    with psycopg.connect(fresh_dsn, autocommit=True) as conn:
        conn.execute("""
            CREATE TABLE cases (
              tenant_id text NOT NULL, case_id text NOT NULL, pack_id text NOT NULL,
              thread_id text NOT NULL, status text NOT NULL,
              payload jsonb NOT NULL DEFAULT '{}'::jsonb, seq bigserial,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              PRIMARY KEY (tenant_id, case_id))
        """)
        conn.execute(
            "INSERT INTO cases (tenant_id, case_id, pack_id, thread_id, status) "
            "VALUES ('default', 'pre-existing', 'kyc-uae', 't', 'approved')"
        )

    assert "alembic_version" not in tables(fresh_dsn)

    ensure_schema_sync(dsn=fresh_dsn)

    assert version(fresh_dsn) == head_revision()
    with psycopg.connect(fresh_dsn, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT status FROM cases WHERE case_id = 'pre-existing'"
        ).fetchone()
    assert row is not None, "adopting the database destroyed its data"
    assert row["status"] == "approved"


def test_the_old_global_bigserial_events_table_is_replaced(fresh_dsn):
    """The one destructive step, and the reason it is allowed.

    `events.seq` as a global sequence silently dropped events. Replacing that
    table is safe where dropping any other would not be, because events are a
    delivery accelerator and never a source of truth.
    """
    with psycopg.connect(fresh_dsn, autocommit=True) as conn:
        conn.execute("""
            CREATE TABLE events (
              seq bigserial PRIMARY KEY, tenant_id text NOT NULL,
              case_id text NOT NULL, kind text NOT NULL, payload jsonb NOT NULL,
              created_at timestamptz NOT NULL DEFAULT now())
        """)

    ensure_schema_sync(dsn=fresh_dsn)

    with psycopg.connect(fresh_dsn, row_factory=dict_row) as conn:
        cols = {
            r["column_name"]: r["column_default"]
            for r in conn.execute(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_name = 'events'"
            ).fetchall()
        }
    assert cols["seq"] is None, "seq is still a sequence; the fix did not apply"
    assert "event_seq" in tables(fresh_dsn), "the per-case counter table is missing"


def test_downgrade_then_upgrade_round_trips(fresh_dsn):
    """A downgrade nobody has ever run is a downgrade that does not work.

    This is the assertion that separates real migrations from a creation script:
    the schema can move in both directions.
    """
    from alembic import command

    from voxgate.service.db import _alembic_config

    ensure_schema_sync(dsn=fresh_dsn)
    assert EXPECTED_TABLES <= tables(fresh_dsn)

    cfg = _alembic_config()
    cfg.attributes["dsn"] = fresh_dsn
    command.downgrade(cfg, "base")

    remaining = tables(fresh_dsn)
    for gone in EXPECTED_TABLES:
        assert gone not in remaining, f"{gone} survived the downgrade"

    ensure_schema_sync(dsn=fresh_dsn)
    assert EXPECTED_TABLES <= tables(fresh_dsn)
    assert version(fresh_dsn) == head_revision()


def test_the_app_can_use_a_database_it_just_migrated(fresh_dsn):
    """End to end: migrate, then actually store and read a case through it."""
    from voxgate.service.store import PgCaseStore

    pool = open_pool_sync(fresh_dsn)
    try:
        ensure_schema_sync(pool)
        store = PgCaseStore(pool)
        store.upsert("t1", {"case_id": "c1", "pack_id": "kyc-uae", "status": "approved"})
        assert store.get("t1", "c1")["status"] == "approved"
    finally:
        pool.close()
