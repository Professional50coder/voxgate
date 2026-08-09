"""Rate limiting, request ids, and what a 500 is allowed to say.

The last of those is the one that matters. Every other test in this suite
asserts a success path; this file asserts that the failure path does not hand a
connection string to whoever triggered it.
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voxgate.service.middleware import RateLimitMiddleware, RequestContextMiddleware


def build(limit=3, window=60.0, paths=("/costly",)):
    app = FastAPI()

    @app.get("/cheap")
    def cheap():
        return {"ok": True}

    @app.post("/costly")
    def costly():
        return {"ok": True}

    @app.get("/costly")
    def costly_read():
        return {"ok": True}

    @app.post("/boom")
    def boom():
        raise RuntimeError(
            "connection to server at 10.0.0.7 port 5432 failed: "
            "password authentication failed for user 'voxgate'"
        )

    # Same order as create_app, and the order is the thing under test.
    # `add_middleware` inserts at the front, so the LAST added is OUTERMOST:
    # rate limit first, request context second, means context wraps the limiter
    # and a 429 still gets an id and a log line.
    app.add_middleware(RateLimitMiddleware, paths=paths, limit=limit, window=window)
    app.add_middleware(RequestContextMiddleware)
    # raise_server_exceptions=False so TestClient returns the response the
    # middleware produced instead of re-raising, which is what a real client sees.
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

def test_costly_requests_are_capped():
    client = build(limit=3)
    for _ in range(3):
        assert client.post("/costly").status_code == 200
    blocked = client.post("/costly")
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"


def test_cheap_paths_are_never_limited():
    client = build(limit=1)
    client.post("/costly")
    for _ in range(20):
        assert client.get("/cheap").status_code == 200


def test_reads_of_a_costly_path_are_not_limited():
    """GET /packs is the catalogue the UI polls. Only the spending verbs cost."""
    client = build(limit=1)
    client.post("/costly")
    for _ in range(10):
        assert client.get("/costly").status_code == 200


def test_the_window_expires():
    client = build(limit=1, window=0.15)
    assert client.post("/costly").status_code == 200
    assert client.post("/costly").status_code == 429
    time.sleep(0.2)
    assert client.post("/costly").status_code == 200


def test_clients_are_counted_separately():
    client = build(limit=1)
    assert client.post("/costly", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert client.post("/costly", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    assert client.post("/costly", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200


def test_idle_clients_are_swept_from_the_table():
    """One entry per address ever seen is a leak an internet scan accelerates.

    Driven against the limiter directly rather than through a client, because
    the bookkeeping under test is invisible from the outside — a leaking table
    answers every request exactly like a healthy one, right up until the process
    runs out of memory.
    """
    limiter = RateLimitMiddleware(_null_app, paths=("/costly",), limit=5, window=0.1)

    for i in range(50):
        assert not limiter._limited(_request(f"10.0.0.{i}"))
    assert len(limiter._hits) == 50

    time.sleep(0.2)
    limiter._limited(_request("10.1.1.1"))
    assert len(limiter._hits) == 1, "stale clients were never dropped"


async def _null_app(scope, receive, send):
    """Never called: the sweep test drives the limiter's own bookkeeping."""


def _request(address):
    from starlette.requests import Request

    return Request({
        "type": "http",
        "method": "POST",
        "path": "/costly",
        "headers": [(b"x-forwarded-for", address.encode())],
        "client": (address, 1234),
    })


# --------------------------------------------------------------------------
# Request ids and error bodies
# --------------------------------------------------------------------------

def test_every_response_carries_a_request_id():
    client = build()
    assert client.get("/cheap").headers["x-request-id"]


def test_a_supplied_request_id_is_echoed():
    """So a trace id from the proxy survives into our logs rather than being
    replaced by one only we can see."""
    client = build()
    r = client.get("/cheap", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_an_unhandled_error_does_not_leak_the_exception_message():
    """The regression this file exists for.

    The handler raises with a host, a port and a username in the text. A client
    gets an id to quote at support, and nothing else; the detail is in the log.
    """
    client = build()
    r = client.post("/boom")

    assert r.status_code == 500
    body = r.text
    for secret in ("10.0.0.7", "5432", "voxgate", "password"):
        assert secret not in body, f"{secret!r} leaked in the 500 body"
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_the_traceback_is_logged_even_though_it_is_not_returned(caplog):
    client = build()
    with caplog.at_level("ERROR"):
        client.post("/boom")
    assert any(r.exc_info for r in caplog.records), (
        "a swallowed exception with no logged traceback is undebuggable"
    )


def test_a_rate_limited_response_still_carries_a_request_id_and_is_logged(caplog):
    """Middleware order, which is counterintuitive and was wrong.

    `add_middleware` inserts at the FRONT, so the last one added is outermost.
    Request-context was added first and rate-limit second, putting the limiter
    OUTSIDE it — so a 429 short-circuited before the context layer was entered
    and got no request id and no access-log line. Exactly the traffic you most
    want to correlate was the traffic with nothing to correlate on. The comment
    in app.py claimed the opposite arrangement.
    """
    client = build(limit=1)
    with caplog.at_level("INFO"):
        assert client.post("/costly").status_code == 200
        limited = client.post("/costly")

    assert limited.status_code == 429
    assert limited.headers.get("x-request-id"), "a 429 must be traceable too"
    assert any("429" in r.getMessage() for r in caplog.records), (
        "a rate-limited request must appear in the access log"
    )
