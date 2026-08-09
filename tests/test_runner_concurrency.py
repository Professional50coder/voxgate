"""Things that only break when two requests overlap.

Sync FastAPI handlers run in a threadpool, so "two requests at once" is the
normal case, not an exotic one. Every failure here was reported by a review as
theoretical and then reproduced.
"""

import threading
import time

import pytest
from langgraph.checkpoint.memory import MemorySaver

from voxgate.service.events import InMemoryEventBus
from voxgate.service.runner import CaseRunner
from voxgate.service.store import InMemoryCaseStore


def make_runner(packs_dir=None, packs=None):
    return CaseRunner(dict(packs or {}), MemorySaver, InMemoryCaseStore(),
                      InMemoryEventBus(), packs_dir=packs_dir)


def seed_packs(tmp_path, count):
    """`count` minimal loadable packs on disk."""
    import textwrap

    for n in range(count):
        d = tmp_path / f"pack_{n}"
        d.mkdir()
        (d / "pack.yaml").write_text(textwrap.dedent(f"""
            pack_id: pack-{n}
            display_name: Pack {n}
            gate_role: Reviewer
            thresholds: {{low: 0.30, high: 0.65}}
        """), encoding="utf-8")
        (d / "prompt.md").write_text("You interview people.", encoding="utf-8")
        (d / "schema.py").write_text(textwrap.dedent("""
            from pydantic import BaseModel
            class Schema(BaseModel):
                amount: float
            REASK_HINTS = {"amount": "How much?"}
        """), encoding="utf-8")
        (d / "checks.py").write_text(textwrap.dedent("""
            from voxgate.packs.base import CheckResult
            def noop(fields):
                return CheckResult(check_name="noop", status="clear", score=0.0, details={})
            noop.check_name = "noop"
            CHECKS = [noop]
        """), encoding="utf-8")
        (d / "scoring.py").write_text(textwrap.dedent("""
            from voxgate.ml.scorecard import Feature, Scorecard
            def build_scorecard(low, high):
                return Scorecard([Feature("amount_risk", 2.0,
                    lambda d: min(d["fields"]["amount"] / 100000, 1.0))], -2.0, low, high)
            FEATURE_FIELD_HINTS = {"amount_risk": "amount"}
        """), encoding="utf-8")
    return tmp_path


def test_reloading_packs_does_not_break_a_concurrent_reader(tmp_path):
    """Regression: `RuntimeError: dictionary changed size during iteration`.

    `reload_packs` inserted into `self.packs` in place while `GET /packs`
    iterated it on another threadpool thread — so publishing a pack, or a
    single `POST /cases` for an unknown id, could 500 an unrelated request.
    The reload now builds new dicts and rebinds, so a reader holds a consistent
    mapping for as long as it needs it.
    """
    seed_packs(tmp_path, 12)
    runner = make_runner(packs_dir=tmp_path)
    assert runner.packs == {}, "starts empty, like a worker that booted first"

    errors: list[str] = []
    stop = threading.Event()

    def read():
        while not stop.is_set():
            try:
                # Exactly what the /packs handler does.
                [(p.pack_id, p.display_name) for p in runner.packs.values()]
                list(runner.graphs.keys())
            except Exception as exc:                      # noqa: BLE001 - the assertion
                errors.append(f"{type(exc).__name__}: {exc}")
                return
            # Yield. A tight loop across four threads starves the writer under
            # the GIL badly enough that the reload never finishes.
            time.sleep(0)

    readers = [threading.Thread(target=read) for _ in range(4)]
    for t in readers:
        t.start()
    try:
        for _ in range(5):
            runner._seen_dirs = set()       # force a genuine reload each time
            runner.reload_packs()
    finally:
        stop.set()
        for t in readers:
            t.join(timeout=10)

    assert not errors, f"a concurrent reader blew up: {errors[0]}"
    assert len(runner.packs) == 12


def test_add_pack_does_not_break_a_concurrent_reader(tmp_path):
    """Same guarantee for the publish path, which registers one pack at a time."""
    from voxgate.packs.loader import load_packs

    seed_packs(tmp_path, 20)
    loaded = load_packs(tmp_path)
    runner = make_runner()

    errors: list[str] = []
    stop = threading.Event()

    def read():
        while not stop.is_set():
            try:
                [p.pack_id for p in runner.packs.values()]
            except Exception as exc:                      # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
                return
            time.sleep(0)

    readers = [threading.Thread(target=read) for _ in range(4)]
    for t in readers:
        t.start()
    try:
        for pack in loaded.values():
            runner.add_pack(pack, object())
    finally:
        stop.set()
        for t in readers:
            t.join(timeout=10)

    assert not errors, f"a concurrent reader blew up: {errors[0]}"
    assert len(runner.packs) == 20


def test_a_case_lock_held_too_long_times_out_rather_than_parking_the_thread():
    """The docstring promised a bounded wait and did not deliver one.

    `LOCK_TIMEOUT` was passed to `pool.connection()`, which bounds acquiring a
    CONNECTION, not the lock; and the in-process lock used a bare `with`, which
    waits forever. A request thread stuck behind a wedged peer never returned.
    """
    runner = make_runner()
    runner.LOCK_TIMEOUT = 0.2

    holder_in = threading.Event()
    release = threading.Event()

    def hold():
        with runner._case_lock("case-1"):
            holder_in.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert holder_in.wait(timeout=5)

    try:
        with pytest.raises(TimeoutError):
            with runner._case_lock("case-1"):
                pytest.fail("acquired a lock another thread is holding")
    finally:
        release.set()
        holder.join(timeout=10)

    # And the lock is usable again afterwards: a timeout must not leak it.
    with runner._case_lock("case-1"):
        pass
