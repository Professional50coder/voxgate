"""Shared request quota.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-07

The first migration after the baseline, and therefore the first one that is NOT
idempotent. 0001 uses `IF NOT EXISTS` because it had to adopt databases created
before migrations existed; copying that habit here would give a migration that
silently does nothing when it was supposed to do something, which is the worst
failure a migration can have, because it reports success.

The table backs `service/quota.py`: one row per (subject, window, endpoint),
incremented atomically so a spend cap holds across workers rather than being
multiplied by their number.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE quota_usage (
  subject      text        NOT NULL,
  window_start timestamptz NOT NULL,
  endpoint     text        NOT NULL,
  used         bigint      NOT NULL DEFAULT 0,
  PRIMARY KEY (subject, window_start, endpoint)
);
""")
    # Purging closed windows scans by window_start alone, and the primary key
    # leads with subject, so it cannot serve that query.
    op.execute("CREATE INDEX quota_usage_window_idx ON quota_usage (window_start)")


def downgrade() -> None:
    """Drops every counter.

    Safe in a way most downgrades are not: the table holds only current-window
    tallies, so losing it resets everyone's usage to zero for the remainder of
    the window and nothing else. No decision, case or audit record depends on it.
    """
    op.execute("DROP TABLE IF EXISTS quota_usage")
