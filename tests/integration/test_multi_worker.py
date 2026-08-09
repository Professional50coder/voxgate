"""What actually happens with more than one worker.

Production runs `uvicorn --workers N` behind a load balancer that does not know
or care which worker served the previous request. Two pieces of state were
per-process and neither failed loudly when split across workers:

  the event bus     worker A publishes, worker B's WebSocket never sees it, and
                    the live view goes quiet with no error at either end
  the pack registry worker A publishes a pack, worker B 404s POST /cases for it

Each test below builds two independent objects against one shared database —
which is exactly what two worker processes are — and asserts the seam holds.
Requires VOXGATE_TEST_DB; skipped otherwise.
"""

import os
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from voxgate.config import Settings
from voxgate.packs.publish import publish_pack
from voxgate.service.app import create_app
from voxgate.service.events import InMemoryEventBus, PgEventBus

TEST_DB = os.environ.get("VOXGATE_TEST_DB")

pytestmark = pytest.mark.skipif(not TEST_DB, reason="VOXGATE_TEST_DB not set")


@pytest.fixture
def pool():
    from voxgate.service.db import ensure_schema_sync, open_pool_sync

    p = open_pool_sync(TEST_DB)
    ensure_schema_sync(p)
    yield p
    p.close()


def test_an_event_published_on_one_worker_reaches_a_socket_on_another(pool):
    """The headline guarantee. Two buses, one database, no shared memory."""
    case_id = f"case-{uuid.uuid4()}"
    worker_a = PgEventBus(pool, poll_interval=0.02)
    worker_b = PgEventBus(pool, poll_interval=0.02)

    got: list[dict] = []
    socket_on_b = threading.Thread(target=lambda: got.extend(worker_b.wait(case_id, 0, 5.0)))
    socket_on_b.start()
    time.sleep(0.05)

    worker_a.publish(case_id, {"kind": "state", "n": 42})
    socket_on_b.join(timeout=6)

    assert not socket_on_b.is_alive(), "the socket on worker B never woke up"
    assert [e["n"] for e in got] == [42]


def test_the_in_memory_bus_cannot_do_this(pool):
    """The reason the Postgres bus is not optional.

    Two in-memory buses are two worker processes. This asserts the failure so
    that swapping the durable bus back out for the in-memory one under multiple
    workers fails a test instead of silently freezing every live view.
    """
    case_id = f"case-{uuid.uuid4()}"
    worker_a, worker_b = InMemoryEventBus(), InMemoryEventBus()

    worker_a.publish(case_id, {"kind": "state", "n": 42})

    assert worker_b.wait(case_id, 0, 0.05) == []
    assert worker_b.history(case_id) == []


def test_a_pack_published_on_one_worker_becomes_runnable_on_another(tmp_path):
    """Publishing writes to disk, which both workers share; the compiled graph
    lives in one process, which they do not. Worker B must notice."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    publish_pack(_spec("seed-pack"), packs_dir)

    settings = Settings(packs_dir=packs_dir, database_url=None)
    worker_a = TestClient(create_app(settings=settings))
    worker_b = TestClient(create_app(settings=settings))

    # Worker B started before the pack existed — the state a rolling deploy or
    # a load balancer leaves you in.
    assert worker_b.post("/cases", json={"pack_id": "late-pack"}).status_code == 404

    published = worker_a.post("/packs/publish", json={"spec": _spec("late-pack")})
    assert published.status_code == 201, published.text

    # No restart, no shared memory: worker B rescans on the miss.
    created = worker_b.post("/cases", json={"pack_id": "late-pack"})
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "awaiting_interview"

    assert "late-pack" in [p["pack_id"] for p in worker_b.get("/packs").json()]


def _spec(pack_id):
    return {
        "pack_id": pack_id,
        "display_name": "Cross Worker Pack",
        "gate_role": "Reviewer",
        "persona": "You are a calm intake interviewer.",
        "gate_reason": "anything unusual",
        "thresholds": {"low": 0.30, "high": 0.65},
        "bias": -2.5,
        "fields": [
            {"name": "full_name", "type": "text",
             "question": "What is your name?", "min_words": 1},
            {"name": "urgency", "type": "enum", "weight": 1.6,
             "question": "How urgent is it?",
             "values": {"routine": 0.1, "urgent": 0.95}},
        ],
        "checks": [
            {"name": "red_flag", "field": "urgency",
             "flags": {"hit": ["urgent"], "review": []}},
        ],
    }


def test_shutdown_closes_every_pool_it_opened(tmp_path):
    """Graceful shutdown, asserted rather than assumed.

    Without it, SIGTERM tore the process down with connections still checked
    out: Postgres logged a wall of unexpected EOFs on every deploy, and the
    checkpointer's own connection — which is not in any pool — was never closed
    at all. TestClient as a context manager runs the lifespan, so this exercises
    the real startup and shutdown path.
    """
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    publish_pack(_spec("shutdown-pack"), packs_dir)

    settings = Settings(packs_dir=packs_dir, database_url=TEST_DB)
    app = create_app(settings=settings)

    with TestClient(app) as client:
        assert client.get("/health/ready").json()["checks"]["database"] == "ok"
        runner = app.state.runner
        store_pool = runner.store._pool
        assert not store_pool.closed
        assert not runner.lock_pool.closed

    assert store_pool.closed, "the store pool outlived the app"
    assert runner.lock_pool.closed, "the lock pool outlived the app"
    assert runner.checkpointer.conn.closed, "the checkpointer connection outlived the app"
