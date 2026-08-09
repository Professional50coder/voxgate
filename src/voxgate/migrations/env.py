"""Alembic environment.

Two things worth knowing:

**The URL comes from the environment, never from alembic.ini.** A connection
string carries a password, and a password in a committed file is a leak that
survives the commit being reverted. `VOXGATE_DATABASE_URL` is read here, using
the same `Settings` object the service uses, so there is exactly one place a
DSN is configured.

**Offline mode is not supported.** It emits SQL to stdout without connecting,
which cannot work here: 0001 uses `CREATE TABLE IF NOT EXISTS` and a `DO` block
whose behaviour depends on what is already in the database. Emitting that as a
script would produce something that looks runnable and is not, which is worse
than refusing.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config


def _url() -> str:
    """The DSN, preferring the one the caller passed in.

    `config.attributes["dsn"]` is set by `ensure_schema_sync` from the pool it
    was given. Preferring it over the environment is what stops a test that
    built a pool against a throwaway database from migrating the developer's
    real one, which is what reading `VOXGATE_DATABASE_URL` unconditionally
    would do.
    """
    from voxgate.config import get_settings

    dsn = config.attributes.get("dsn") or get_settings().database_url
    if not dsn:
        raise RuntimeError(
            "VOXGATE_DATABASE_URL is not set; there is no database to migrate"
        )
    # SQLAlchemy needs the driver named explicitly. The service itself uses
    # psycopg directly and does not care, so this rewrite lives here rather
    # than in Settings, where it would leak an Alembic detail into the app.
    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return dsn


def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", _url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            # No SQLAlchemy models exist to diff against: the application talks
            # to Postgres through psycopg directly. Every migration is written
            # by hand, which this makes explicit rather than leaving as a
            # surprise when autogenerate produces an empty diff.
            target_metadata=None,
            compare_type=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        "offline migrations are not supported: 0001 is conditional on existing "
        "database state and cannot be emitted as a static script"
    )

run_migrations_online()
