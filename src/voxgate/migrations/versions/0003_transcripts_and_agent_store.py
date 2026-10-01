"""Transcripts and the agent store move into Postgres.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01

Two things that lived on local disk, which a serverless host does not have:

  transcript_turns / transcript_sessions
      Every interview's words and its summary. On Vercel the only writable path
      is a per-instance /tmp, so transcripts were silently lost; a reviewer and
      an auditor need them. `tsv` is a generated full-text column so search is
      a GIN index lookup, not a scan.

  published_packs
      Agents published from the builder. The repository's packs/ directory is
      read-only on a serverless host, so publishing could not persist. The spec
      (data, never code) is stored here and every instance regenerates the pack
      from it with the same deterministic generator the CLI uses.

Not idempotent, on purpose: see 0002.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE transcript_sessions (
  tenant_id   text        NOT NULL,
  case_id     text        NOT NULL,
  session_id  text        NOT NULL,
  channel     text        NOT NULL DEFAULT 'web',
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  summary     jsonb,
  PRIMARY KEY (tenant_id, case_id, session_id)
);
""")
    op.execute("""
CREATE TABLE transcript_turns (
  tenant_id   text        NOT NULL,
  case_id     text        NOT NULL,
  session_id  text        NOT NULL,
  turn_no     integer     NOT NULL,
  ts          timestamptz NOT NULL DEFAULT now(),
  offset_ms   integer     NOT NULL DEFAULT 0,
  role        text        NOT NULL,
  text        text        NOT NULL,
  tsv         tsvector    GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
  PRIMARY KEY (tenant_id, case_id, session_id, turn_no)
);
""")
    op.execute("CREATE INDEX transcript_turns_tsv_idx ON transcript_turns USING gin (tsv)")
    op.execute("""
CREATE TABLE published_packs (
  tenant_id    text        NOT NULL,
  pack_id      text        NOT NULL,
  display_name text        NOT NULL,
  spec         jsonb       NOT NULL,
  created_by   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, pack_id)
);
""")


def downgrade() -> None:
    """Drops transcripts and published agents. Destructive: export first."""
    op.execute("DROP TABLE IF EXISTS published_packs")
    op.execute("DROP TABLE IF EXISTS transcript_turns")
    op.execute("DROP TABLE IF EXISTS transcript_sessions")
