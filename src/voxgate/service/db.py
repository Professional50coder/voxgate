"""Postgres connection pool and schema.

The checkpointer already makes a *case's workflow state* durable. What was not
durable was everything around it: the case index the board reads, the event
stream the UI subscribes to, and the run records. All three lived in process
memory, so a restart wiped the board even though the checkpoints survived.

The `cases` table is a **projection** of graph state, never a second source of
truth. `_sync()` rewrites rows from `graph.get_state()`; the checkpointer stays
authoritative. That is what makes it safe to have both an in-memory and a
Postgres implementation: neither owns truth, so they cannot disagree about it.
"""

from __future__ import annotations

import threading
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

# autocommit and prepare_threshold=0 are NOT optional. They are what
# AsyncPostgresSaver.from_conn_string sets internally, and transaction-pooling
# proxies (pgbouncer, Neon's pooled endpoint) break without them.
_POOL_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}


async def open_pool(dsn: str, *, min_size: int = 2, max_size: int = 20) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(dsn, min_size=min_size, max_size=max_size,
                              open=False, kwargs=_POOL_KWARGS)
    await pool.open()
    return pool


def open_pool_sync(dsn: str, *, min_size: int = 1, max_size: int = 5) -> ConnectionPool:
    """Synchronous pool, for the current sync service and for tests.

    The async pool arrives with the async runner in a later task; until then the
    service is synchronous end to end and mixing the two would mean running an
    event loop inside a request thread.
    """
    pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size,
                         open=False, kwargs=_POOL_KWARGS)
    pool.open()
    return pool


def _alembic_config():
    """Alembic config pointing at the migrations shipped inside the package.

    Package-relative, not repo-relative: an installed `voxgate` carries its own
    migrations, so a deployment does not need a working copy of the repository
    to bring its schema up to date.
    """
    from alembic.config import Config

    here = Path(__file__).resolve().parents[1] / "migrations"
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here))
    return cfg


_migration_lock = threading.Lock()


def ensure_schema_sync(pool: ConnectionPool | None = None,
                       dsn: str | None = None) -> None:
    """Bring the schema to head. Safe to call on every start.

    Runs Alembic rather than a `CREATE TABLE IF NOT EXISTS` script, which is the
    difference between creating a schema and migrating one: the old script could
    only ever add tables, so the first change that had to preserve data had no
    path at all.

    Adopting an existing database needs no ceremony because revision 0001 is
    itself idempotent — it was written to be able to run against the databases
    the old script had already created. Alembic stamps `alembic_version` on the
    way through, and every migration after 0001 is a real change.

    Alembic opens its own connection rather than borrowing from `pool`, because
    a migration may need to run outside the transaction and prepared-statement
    settings this pool is configured for. The DSN is taken FROM the pool though,
    which matters more than it looks: tests build a pool against a throwaway
    database, and an Alembic run that resolved its own URL from the environment
    would happily migrate the developer's real database instead.
    """
    from alembic import command

    if dsn is None and pool is not None:
        dsn = pool.conninfo
    cfg = _alembic_config()
    if dsn:
        cfg.attributes["dsn"] = dsn

    # One process can call this from several places at start-up, and two
    # concurrent `upgrade head` runs race on the version table.
    with _migration_lock:
        command.upgrade(cfg, "head")


async def ensure_schema(pool: AsyncConnectionPool | None = None,
                        dsn: str | None = None) -> None:
    """Async-facing wrapper. Alembic is synchronous, so this runs it in a thread
    rather than blocking the event loop for the length of a migration."""
    import asyncio

    if dsn is None and pool is not None:
        dsn = pool.conninfo
    await asyncio.to_thread(ensure_schema_sync, None, dsn)


def make_checkpointer_sync(dsn: str):
    """PostgresSaver on its own connection.

    Deliberately not sharing the pool: the saver holds its own connection for
    the life of the process and expects to manage it. `setup()` must be called
    explicitly the first time, per its own docstring.
    """
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    conn = psycopg.connect(dsn, autocommit=True, prepare_threshold=0)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver
