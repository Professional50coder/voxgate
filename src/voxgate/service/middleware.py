"""Operational middleware: request logging and rate limiting.

Neither is a feature. Both are the difference between an incident you can
diagnose and one you can only guess at, and between a public endpoint that
costs money and one that costs unbounded money.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("voxgate.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Give every request an id, log its outcome, and never leak a traceback.

    The id goes out in `X-Request-ID` and into the log line, so a user reporting
    "it failed at 14:32" hands you the exact request. An unhandled exception is
    logged with its traceback and answered with the id and nothing else: the
    default FastAPI 500 body is fine, but anything that reaches a client here is
    a place a DSN or a prompt fragment can escape, and this file is the one
    chokepoint where that can be guaranteed not to happen.
    """

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request failed",
                extra={"request_id": request_id, "path": request.url.path},
            )
            logger.info(
                '%s %s 500 %.1fms id=%s',
                request.method, request.url.path, elapsed_ms, request_id,
            )
            return JSONResponse(
                {"detail": "internal error", "request_id": request_id},
                status_code=500,
                headers={"X-Request-ID": request_id},
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            '%s %s %d %.1fms id=%s',
            request.method, request.url.path, response.status_code,
            elapsed_ms, request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """A cap on the endpoints that cost real money.

    `/packs/draft`, `/packs/{id}/extract` and `/packs/publish` each spend an LLM
    call or write generated Python to disk. Drafting and publishing are behind
    the operator key now, but a cap is still needed: authentication says who is
    spending, not how much, and the loop that burns a day's Groq quota in a
    minute is far more often a bug in an operator's own script than an attack.
    Extraction is on the applicant path and has no key at all.

    TWO LAYERS, and they do different jobs.

    The burst window here is per process and stays that way on purpose: it is
    the cheap first line that stops a runaway loop within seconds and without a
    round trip. It is not a quota — with N workers its effective ceiling is N
    times what is configured, which makes it useless for counting.

    `quota` is the counting layer, backed by Postgres, shared across every
    worker and attached to the operator key rather than to a socket. See
    `service/quota.py` for why that needed authentication to exist first. When
    it is not configured (no database), the burst window is all there is, which
    is the correct amount of machinery for a single-process dev run.

    The burst window is keyed on the client address, which behind a proxy is the
    proxy unless it sets `X-Forwarded-For`. The first hop of that header is used
    when present; it is spoofable by design, which is acceptable for a burst cap
    and is exactly why the durable quota keys on the API key instead.
    """

    def __init__(self, app, *, paths: tuple[str, ...], limit: int, window: float,
                 quota=None):
        super().__init__(app)
        self._paths = paths
        self._limit = limit
        self._window = window
        self._quota = quota
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = time.monotonic()

    def _client(self, request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _limited(self, request) -> bool:
        path = request.url.path
        if not any(path.startswith(p) for p in self._paths):
            return False
        if request.method == "GET":
            return False

        now = time.monotonic()
        self._sweep(now)
        key = self._client(request)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return True
        hits.append(now)
        return False

    def _sweep(self, now: float) -> None:
        """Drop clients that have gone quiet.

        Without this the dict holds one entry per address ever seen — a slow
        leak that a scan of the internet turns into a fast one. Sweeping on a
        timer rather than every request keeps the common path to one dict
        lookup.
        """
        if now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        stale = [k for k, hits in self._hits.items()
                 if not hits or now - hits[-1] > self._window]
        for key in stale:
            del self._hits[key]

    def _matches(self, request) -> bool:
        path = request.url.path
        return request.method != "GET" and any(path.startswith(p) for p in self._paths)

    async def dispatch(self, request, call_next):
        if self._limited(request):
            logger.warning("rate limited %s %s", self._client(request), request.url.path)
            return JSONResponse(
                {"detail": "too many requests"},
                status_code=429,
                headers={"Retry-After": str(int(self._window))},
            )

        if self._quota is not None and self._matches(request):
            from .quota import subject_for

            subject = subject_for(
                request.headers.get("x-api-key"), self._client(request)
            )
            # to_thread: the pool is blocking, and blocking the event loop here
            # would stall every other request this worker is serving.
            decision = await asyncio.to_thread(
                self._quota.check_and_count, subject, request.url.path
            )
            if not decision.allowed:
                logger.warning(
                    "quota exhausted for %s on %s (%d/%d)",
                    subject, request.url.path, decision.used, decision.limit,
                )
                return JSONResponse(
                    {
                        "detail": "quota exhausted",
                        "used": decision.used,
                        "limit": decision.limit,
                    },
                    status_code=429,
                    headers={"Retry-After": str(decision.resets_in)},
                )
            response = await call_next(request)
            # Standard headers, so a client can back off before being refused
            # rather than discovering the ceiling by hitting it.
            response.headers["X-Quota-Limit"] = str(decision.limit)
            response.headers["X-Quota-Remaining"] = str(decision.remaining)
            return response

        return await call_next(request)
