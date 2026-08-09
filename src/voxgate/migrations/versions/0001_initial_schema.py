"""Initial schema: cases, events, event_seq, runs.

Revision ID: 0001
Revises:
Create Date: 2026-08-07

THE BASELINE, AND THE ONLY IDEMPOTENT MIGRATION.

This schema existed before migrations did — it was created by a
`CREATE TABLE IF NOT EXISTS` script run at startup. So this revision has to be
able to adopt a database that already has every one of these tables, with data
in them, without touching that data. `IF NOT EXISTS` throughout is what makes
that safe: running it against a populated database is a no-op.

That property is exactly why this file is a bad template. Every migration after
it is a real `ALTER` against real rows and must say precisely what it does to
them, in both directions. Copying the `IF NOT EXISTS` habit forward would give
you migrations that silently do nothing when they were supposed to do something,
which is the worst failure a migration can have: it reports success.

The one destructive step is guarded and deliberate. `events.seq` was originally
a global `bigserial`, which silently dropped events — a sequence allocates
before commit, so rows can become visible out of seq order and a cursor-based
poller skips whatever commits behind it. Measured at ~1.2% loss. Dropping and
recreating that table is safe where dropping any other would not be, because
events are a delivery accelerator and never a source of truth: every event
carries state re-derivable from the checkpointer, so `GET /cases/{id}` stays
authoritative.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS cases (
  tenant_id   text        NOT NULL,
  case_id     text        NOT NULL,
  pack_id     text        NOT NULL,
  thread_id   text        NOT NULL,
  status      text        NOT NULL,
  payload     jsonb       NOT NULL DEFAULT '{}'::jsonb,
  seq         bigserial,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, case_id)
);
""")
    # The reviewer queue is "open cases for my tenant, newest first". Indexed
    # for exactly that, because it is the query the board runs on every load.
    op.execute(
        "CREATE INDEX IF NOT EXISTS cases_queue_idx ON cases (tenant_id, status, seq DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS cases_pack_idx ON cases (tenant_id, pack_id, seq DESC)"
    )

    # Retire the global-bigserial events table. See the module docstring for
    # why dropping this one specifically is safe.
    op.execute("""
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'events' AND column_name = 'seq'
      AND column_default LIKE 'nextval%'
  ) THEN
    DROP TABLE events;
  END IF;
END $$;
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS events (
  tenant_id  text        NOT NULL,
  case_id    text        NOT NULL,
  seq        bigint      NOT NULL,
  kind       text        NOT NULL,
  payload    jsonb       NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, case_id, seq)
);
""")

    # One counter row per case. `publish` bumps it and inserts the event in ONE
    # transaction, so the row lock taken by the bump is held until the event is
    # committed: the next writer for that case cannot obtain a seq until the
    # previous event is visible.
    op.execute("""
CREATE TABLE IF NOT EXISTS event_seq (
  tenant_id text   NOT NULL,
  case_id   text   NOT NULL,
  next_seq  bigint NOT NULL,
  PRIMARY KEY (tenant_id, case_id)
);
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS runs (
  run_id     text PRIMARY KEY,
  tenant_id  text        NOT NULL,
  case_id    text,
  pack_id    text        NOT NULL,
  status     text        NOT NULL,
  error      text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS runs_case_idx ON runs (tenant_id, case_id, created_at DESC)"
    )
    # Partial index: boot-time orphan recovery only ever asks for unfinished
    # runs, so indexing the finished ones would be dead weight.
    op.execute("""
CREATE INDEX IF NOT EXISTS runs_alive_idx ON runs (status)
  WHERE status IN ('pending', 'running');
""")


def downgrade() -> None:
    """Drop everything this created.

    Every case, event and run. Written out because a downgrade that quietly
    leaves tables behind is worse than one that refuses — but the checkpointer's
    own tables are not touched here, so case *state* survives this and only the
    projections are lost.
    """
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TABLE IF EXISTS event_seq")
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS cases")
