"""Shared quota, counted in Postgres so every worker sees the same total.

The in-process limiter in `middleware.py` is still there and still useful: it is
the cheap first line that stops a runaway loop without a round trip. What it
cannot do is count. With N workers the effective limit is N times whatever is
configured, so "200 drafts a day" means 200 on a laptop and 800 in production,
which is not a quota — it is a coincidence.

This is the counting layer. One row per (subject, window, endpoint), incremented
atomically, so it holds across workers and across machines.

**Why it needed auth to exist first.** A quota has to be attached to someone.
Before there were keys, the only identity available was an IP address, which is
spoofable through `X-Forwarded-For` and shared by everyone behind a NAT — so a
per-IP quota either punished a whole office or could be reset by anyone who
cared. An operator key is a real subject: it survives an IP change, it is
distinct per holder, and rotating it is a deliberate act. Requests with no key
fall back to the address, which keeps the applicant surface metered without
pretending that number means more than it does.

**Fixed windows, not sliding.** A sliding window needs either a row per request
or a sorted structure to trim, and this table is written on the request path of
the slowest endpoints in the service. A fixed window is one `INSERT ... ON
CONFLICT DO UPDATE` and one row per subject per window. The known cost is that a
caller can spend two windows' worth of budget across a boundary; for a spend cap
that is a rounding error, and for anything where it would not be, this is the
wrong mechanism entirely.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Per key per day. Generous: this is a runaway-and-abuse ceiling, not a pricing
# tier, and an operator legitimately exploring the authoring flow should never
# meet it.
DEFAULT_DAILY_LIMIT = 500
DEFAULT_WINDOW_SECONDS = 24 * 60 * 60


@dataclass
class QuotaDecision:
    allowed: bool
    used: int
    limit: int
    resets_in: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def subject_for(api_key: str | None, address: str) -> str:
    """Who is being metered.

    The key is hashed rather than stored: this table is read by anyone with
    database access and by anyone reading a slow-query log, and a quota counter
    is not a reason for a credential to exist in either. The hash is stable, so
    the count follows the key across IP changes, which is the whole point of
    metering a subject rather than a socket.
    """
    if api_key:
        return "key:" + hashlib.sha256(api_key.encode()).hexdigest()[:32]
    return "addr:" + address


class PgQuota:
    """Counts requests per subject per fixed window."""

    def __init__(self, pool, *, limit: int = DEFAULT_DAILY_LIMIT,
                 window_seconds: int = DEFAULT_WINDOW_SECONDS) -> None:
        self._pool = pool
        self._limit = limit
        self._window = window_seconds

    def _window_start(self, now: float) -> int:
        return int(now // self._window) * self._window

    def check_and_count(self, subject: str, endpoint: str) -> QuotaDecision:
        """Record one request and say whether it was within the quota.

        Counting happens in the same statement as the read, so two workers
        cannot both see "one under the limit" and both allow. `RETURNING used`
        gives the post-increment value, which means the caller that pushes the
        count to limit+1 is the one refused — the limit is a ceiling on
        successful requests, not on attempts.
        """
        now = time.time()
        window_start = self._window_start(now)
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO quota_usage (subject, window_start, endpoint, used)
                    VALUES (%s, to_timestamp(%s), %s, 1)
                    ON CONFLICT (subject, window_start, endpoint)
                    DO UPDATE SET used = quota_usage.used + 1
                    RETURNING used
                    """,
                    (subject, window_start, endpoint),
                ).fetchone()
                used = int(row["used"])
        except Exception:
            # Fail OPEN, loudly. This is a cost control, not an authorization
            # check: refusing every request because the counter is unreachable
            # turns a metering outage into a service outage, and the in-process
            # limiter is still standing in front of this.
            logger.warning("quota check failed; allowing the request", exc_info=True)
            return QuotaDecision(True, 0, self._limit, self._window)

        return QuotaDecision(
            allowed=used <= self._limit,
            used=used,
            limit=self._limit,
            resets_in=int(window_start + self._window - now),
        )

    def usage(self, subject: str) -> dict[str, int]:
        """Current window's usage per endpoint. For an operator to see where it
        went, rather than only that it ran out."""
        window_start = self._window_start(time.time())
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT endpoint, used FROM quota_usage "
                "WHERE subject = %s AND window_start = to_timestamp(%s)",
                (subject, window_start),
            ).fetchall()
        return {r["endpoint"]: int(r["used"]) for r in rows}

    def purge_expired(self) -> int:
        """Drop windows that have closed.

        Without this the table grows one row per subject per window forever.
        Cheap enough to call from readiness, which is the only thing guaranteed
        to be called regularly on every deployment.
        """
        cutoff = self._window_start(time.time())
        with self._pool.connection() as conn:
            result = conn.execute(
                "DELETE FROM quota_usage WHERE window_start < to_timestamp(%s)",
                (cutoff,),
            )
            return result.rowcount or 0
