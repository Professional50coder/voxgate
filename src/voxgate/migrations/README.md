# Migrations

Alembic, living inside the package rather than at the repo root, so a deployment
that installs `voxgate` gets its migrations with it and `alembic upgrade` needs
no working copy of this repository.

Run them by starting the service: `create_app` calls `ensure_schema_sync`, which
runs `upgrade head`. There is nothing to remember to do.

## Adding one

```bash
uv run alembic -c src/voxgate/migrations/alembic.ini revision -m "add a column"
```

Then write the `upgrade()` body by hand. Autogenerate is deliberately not wired
up: this schema has no SQLAlchemy models to diff against, because the
application talks to Postgres through psycopg directly.

## The one rule

**0001 is idempotent. Nothing after it may be.**

0001 uses `CREATE TABLE IF NOT EXISTS` so that a database created before
migrations existed can adopt them without being dropped — running it against a
populated database is a no-op that leaves the data alone. That property is what
makes the baseline safe, and it is also what makes it useless as a template:
every later migration is a real `ALTER` against real rows and must say exactly
what it does to them, including in `downgrade()`.
