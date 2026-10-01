import hashlib
import logging
import threading
import time
import uuid
from contextlib import contextmanager

from langgraph.types import Command

logger = logging.getLogger(__name__)

class CaseRunner:
    DEFAULT_TENANT = "default"

    # A resume that cannot take its lock in this long has a stuck peer, not a
    # busy one. Failing is better than a request thread parked forever.
    LOCK_TIMEOUT = 15.0
    # How often to re-attempt the advisory lock while waiting it out.
    LOCK_POLL = 0.05

    # Seconds between agent-store checks on the listing path. A miss for a
    # specific pack checks immediately; see has_pack.
    STORE_SYNC_INTERVAL = 10.0

    def __init__(self, packs, checkpointer_factory, store, bus, tenant=None,
                 packs_dir=None, lock_pool=None, published_dir=None, pack_store=None):
        self.packs, self.store, self.bus = packs, store, bus
        # Published agents: written here (writable even where packs_dir is
        # not, e.g. /tmp on Vercel) and regenerated from `pack_store` on every
        # instance, so an agent published through one is runnable on all.
        self.published_dir = published_dir if published_dir != packs_dir else None
        if self.published_dir is not None:
            try:
                self.published_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.warning("cannot create %s", self.published_dir, exc_info=True)
        self.pack_store = pack_store
        self._last_store_sync = 0.0
        # Where packs live on disk, so a pack published by another worker can be
        # picked up. None disables rescanning, which is what tests that build a
        # runner from a fixed dict want.
        self.packs_dir = packs_dir
        # Pack directory names seen by the last scan. A miss compares against
        # this before doing any import work.
        self._seen_dirs: set[str] = set()
        # One lock per case, created on demand. Unbounded in principle; in
        # practice one small Lock per case this process has ever advanced, which
        # is the same order as the checkpoints it has written.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # A pool of its own, NOT the store's. An advisory lock is held for the
        # length of the graph invocation, and the work done under it needs the
        # store — so borrowing the store's pool means each in-flight resume
        # holds one connection while waiting for a second. At five concurrent
        # resumes against a five-connection pool that deadlocks outright, which
        # a standalone reproduction confirmed before this was split out.
        self.lock_pool = lock_pool
        # Tenancy is schema-ready but auth is not built, so every case lands in
        # one tenant for now. Threading it through here rather than hardcoding
        # it at each call site means enabling real tenancy later is a change to
        # the caller, not a sweep through this file.
        self.tenant = tenant or self.DEFAULT_TENANT
        # Retained so a pack published at runtime can be given its own compiled
        # graph on the same checkpointer. Without this, publishing writes a pack
        # to disk that POST /cases cannot then run.
        self.checkpointer = checkpointer_factory()
        from voxgate.graph.build import build_graph
        self.graphs = {pid: build_graph(p, self.checkpointer) for pid, p in packs.items()}

    def has_pack(self, pack_id):
        """True if this worker can run `pack_id`, rescanning disk once if not.

        Packs are compiled into graphs at construction and held per process, so
        a pack published through worker A did not exist on worker B: the pack
        was on disk and in the catalogue, but `POST /cases` against it 404'd on
        whichever worker the load balancer happened to pick. Publishing is rare
        and a miss is cheap, so the miss path reloads rather than requiring a
        rolling restart after every publish.
        """
        if pack_id in self.packs:
            return True
        self.refresh_packs(force_store=True)
        return pack_id in self.packs

    def _pack_dirs(self):
        return [d for d in (self.packs_dir, self.published_dir) if d is not None]

    def sync_store(self, force=False):
        """Write any agent in the store that this instance lacks to disk.

        The store holds specs (data); the pack is regenerated from it with the
        same deterministic generator publishing uses, so every instance runs
        byte-identical code without code ever being stored or shipped.
        """
        target = self.published_dir or self.packs_dir
        if self.pack_store is None or target is None:
            return
        now = time.monotonic()
        if not force and now - self._last_store_sync < self.STORE_SYNC_INTERVAL:
            return
        self._last_store_sync = now
        from voxgate.packs.publish import publish_pack
        try:
            specs = self.pack_store.specs(self.tenant)
        except Exception:
            logger.warning("agent store unavailable", exc_info=True)
            return
        for spec in specs:
            directory = target / spec["pack_id"].replace("-", "_")
            if (directory / "pack.yaml").exists():
                continue
            try:
                publish_pack(spec, target, overwrite=True)
            except Exception:
                logger.warning("could not materialise %s", spec.get("pack_id"), exc_info=True)

    def refresh_packs(self, force_store=False):
        """Load any pack directory that has appeared since the last scan.

        Gated on a directory listing rather than a timer. A timer is wrong in
        both directions here: it lets an anonymous client turn a stream of 404s
        into repeated imports, and — the reason the first attempt failed a test
        — it also makes a pack published a moment ago stay 404 on every other
        worker until the interval expires, which is precisely the window a user
        clicks through.

        A listing is one cheap call, exact, and immune to filesystem timestamp
        granularity. Nothing new on disk means no import work.
        """
        if self.packs_dir is None:
            return self.packs
        self.sync_store(force=force_store)
        on_disk = set()
        for d in self._pack_dirs():
            try:
                on_disk |= {
                    f"{d}:{child.name}"
                    for child in d.iterdir()
                    if child.is_dir() and (child / "pack.yaml").exists()
                }
            except OSError:
                # A packs directory can be missing in a half-provisioned
                # deploy. Serving the packs already compiled beats failing.
                logger.warning("could not list %s", d, exc_info=True)
        if on_disk == self._seen_dirs:
            return self.packs
        self._seen_dirs = on_disk
        return self.reload_packs()

    def reload_packs(self):
        """Pick up packs written to disk since this process started.

        Additive: an existing pack keeps the graph it already has, so a case
        mid-interview is never handed a freshly compiled graph underneath it.

        Copy-on-write, not in-place mutation. Sync FastAPI handlers run in a
        threadpool, so `GET /packs` genuinely iterates `self.packs` on another
        thread while a `POST /cases` miss triggers this reload -- and inserting
        into the dict under it raised `RuntimeError: dictionary changed size
        during iteration`, turning an unrelated request into a 500. Building new
        dicts and rebinding means a reader sees either the old mapping or the
        new one, never one mid-write.
        """
        from voxgate.graph.build import build_graph
        from voxgate.packs.loader import load_packs

        packs = dict(self.packs)
        graphs = dict(self.graphs)
        for d in self._pack_dirs():
            if not d.exists():
                continue
            for pack_id, pack in load_packs(d).items():
                if pack_id not in packs:
                    packs[pack_id] = pack
                    graphs[pack_id] = build_graph(pack, self.checkpointer)
        self.packs, self.graphs = packs, graphs
        return self.packs

    def add_pack(self, pack, graph):
        """Register one pack without mutating a mapping a reader may hold.

        Same reasoning as `reload_packs`: publish runs on a request thread while
        `GET /packs` may be iterating right now.
        """
        self.packs = {**self.packs, pack.pack_id: pack}
        self.graphs = {**self.graphs, pack.pack_id: graph}

    def _cfg(self, case_id):
        return {"configurable": {"thread_id": case_id}}

    @contextmanager
    def _case_lock(self, case_id):
        """Hold the right to advance one case's graph.

        Two layers, because one process is not the deployment target:

          in-process  a `threading.Lock` per case. Enough for a single worker,
                      which is what `uvicorn` runs by default.
          Postgres    a session-level advisory lock keyed on the case id, taken
                      only when `lock_pool` is configured. This is what makes
                      the guarantee hold across workers and across machines,
                      where a local lock is worthless.

        Advisory locks are released explicitly rather than left to connection
        teardown: the connection goes back to a pool and would carry the lock
        with it, deadlocking the next borrower of that connection.
        """
        with self._locks_guard:
            lock = self._locks.setdefault(case_id, threading.Lock())

        # Both acquisitions are bounded. The previous version passed
        # LOCK_TIMEOUT to `pool.connection()`, which bounds getting a
        # CONNECTION and not the lock wait at all, and used a bare `with lock`.
        # So the promise below -- that a stuck peer fails rather than parking a
        # request thread forever -- was not true in either layer.
        deadline = time.monotonic() + self.LOCK_TIMEOUT
        if not lock.acquire(timeout=self.LOCK_TIMEOUT):
            raise TimeoutError(f"timed out waiting to advance case {case_id}")
        try:
            if self.lock_pool is None:
                yield
                return
            # Postgres advisory locks are keyed by bigint, so hash the case id
            # into the signed 64-bit range. A collision costs two unrelated
            # cases some serialisation, never correctness.
            key = int.from_bytes(
                hashlib.blake2b(case_id.encode(), digest_size=8).digest(),
                "big", signed=True,
            )
            remaining = max(deadline - time.monotonic(), 0.0)
            with self.lock_pool.connection(timeout=max(remaining, 1.0)) as conn:
                # pg_try_advisory_lock in a bounded poll, not pg_advisory_lock:
                # the blocking form waits forever and honours no timeout here.
                while True:
                    got = conn.execute(
                        "SELECT pg_try_advisory_lock(%s) AS ok", (key,)
                    ).fetchone()["ok"]
                    if got:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"timed out waiting to advance case {case_id}"
                        )
                    time.sleep(self.LOCK_POLL)
                try:
                    yield
                finally:
                    # Explicit: the connection goes back to the pool and would
                    # carry a session lock with it, wedging the next borrower.
                    conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
        finally:
            lock.release()

    def _sync(self, case_id, pack_id):
        graph = self.graphs[pack_id]
        snap = graph.get_state(self._cfg(case_id))
        v = snap.values
        pending = None
        for task in snap.tasks:
            if task.interrupts:
                pending = task.interrupts[0].value
        case = {"case_id": case_id, "pack_id": pack_id,
                "status": v.get("status", "processing"),
                "fields": v.get("fields", {}),
                "score": v.get("score"), "decision": v.get("decision"),
                "check_results": v.get("check_results", []),
                "audit": v.get("audit", []),
                "interrupt": pending}
        self.store.upsert(self.tenant, case)
        self.bus.publish(case_id, {"kind": "state", "case": self.store.get(self.tenant, case_id)})
        return self.store.get(self.tenant, case_id)

    def _mark_needs_attention(self, case_id, pack_id, e):
        # The exception message went into the case and straight back out of the
        # API. A node failing inside psycopg or an LLM client raises with a DSN,
        # a host and user, or a prompt fragment in the text; an applicant-facing
        # surface reads this field. The type is enough for a reviewer to know
        # something broke, and the full traceback is logged for whoever fixes it.
        logger.exception("case %s failed on pack %s", case_id, pack_id)
        self.store.upsert(self.tenant, {"case_id": case_id, "pack_id": pack_id,
                           "status": "needs_attention",
                           "error": type(e).__name__})
        self.bus.publish(case_id, {"kind": "state", "case": self.store.get(self.tenant, case_id)})
        return self.store.get(self.tenant, case_id)

    def start_case(self, pack_id):
        case_id = str(uuid.uuid4())
        self.store.upsert(self.tenant, {"case_id": case_id, "pack_id": pack_id,
                           "status": "awaiting_interview", "live_fields": {}})
        try:
            self.graphs[pack_id].invoke(
                {"case_id": case_id, "pack_id": pack_id, "reask_count": 0}, self._cfg(case_id))
        except Exception as e:
            return self._mark_needs_attention(case_id, pack_id, e)
        return self._sync(case_id, pack_id)

    def _pack_of(self, case_id):
        case = self.store.get(self.tenant, case_id)
        if case is None:
            raise KeyError(case_id)
        return case["pack_id"]

    def resume(self, case_id, payload):
        pack_id = self._pack_of(case_id)
        if not self.has_pack(pack_id):
            # The case outlived this worker's view of its pack: either the pack
            # was published elsewhere, or the case predates a restart.
            raise KeyError(pack_id)
        # Serialised per case. Two resumes racing the same interrupt both read
        # the same checkpoint, both invoke, and the second overwrites the first
        # — a double-submitted review form silently discarding a decision.
        with self._case_lock(case_id):
            try:
                self.graphs[pack_id].invoke(Command(resume=payload), self._cfg(case_id))
            except Exception as e:
                return self._mark_needs_attention(case_id, pack_id, e)
            return self._sync(case_id, pack_id)

    def recover_case(self, case_id, pack_id):
        """Rehydrate the store entry for a case that exists only in the checkpointer.

        NOTE (list_known_threads): a full store rebuild on boot — enumerating every
        thread_id known to the checkpointer and re-syncing each one — is a Plan 3
        concern (the dashboard needs it, once one exists). For now `recover_case`
        is the explicit per-case recovery path: the caller already knows the
        case_id and pack_id (e.g. from a URL or an external record), and this
        integration test is its consumer.
        """
        self.store.upsert(self.tenant, {"case_id": case_id, "pack_id": pack_id, "live_fields": {}})
        return self._sync(case_id, pack_id)

    def patch_fields(self, case_id, fields, confidence):
        pack_id = self._pack_of(case_id)
        case = self.store.get(self.tenant, case_id)
        live = {**case.get("live_fields", {}), **fields}
        self.store.upsert(self.tenant, {"case_id": case_id, "pack_id": pack_id, "live_fields": live})
        self.bus.publish(case_id, {"kind": "fields", "fields": live, "confidence": confidence})
        return self.store.get(self.tenant, case_id)
