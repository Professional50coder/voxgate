### Task 9: Postgres durability integration test + demo script + docs

**Files:**
- Create: `tests/integration/test_postgres_resume.py`, `scripts/demo_case.py`, `README.md`, `.paul/PROJECT.md`, `.paul/STATE.md`

**Interfaces:**
- Consumes: everything.
- Produces: the "kill the server, come back, approve the case" proof, a runnable demo, and project docs.

- [ ] **Step 1: Write the integration test** — `tests/integration/test_postgres_resume.py` (skipped unless `VOXGATE_TEST_DB` is set; run `docker compose up -d` first and set `VOXGATE_TEST_DB=postgresql://voxgate:voxgate@localhost:5433/voxgate`)

```python
import os
import pytest
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.app import _postgres_factory
from voxgate.service.runner import CaseRunner
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus
from tests.test_pack_kyc_uae import RISKY

DSN = os.environ.get("VOXGATE_TEST_DB")
pytestmark = pytest.mark.skipif(not DSN, reason="VOXGATE_TEST_DB not set")

def _fresh_runner():
    return CaseRunner(load_packs(get_settings().packs_dir),
                      lambda: _postgres_factory(DSN), CaseStore(), EventBus())

def test_case_survives_process_restart():
    r1 = _fresh_runner()
    case = r1.start_case("kyc-uae")
    r1.resume(case["case_id"], {"fields": RISKY, "confidence": {}})
    assert r1.store.get(case["case_id"])["status"] == "awaiting_review"

    r2 = _fresh_runner()                    # brand-new runner = restarted process
    # store is empty in r2 (in-memory index) — recover from the checkpointer:
    recovered = r2.recover_case(case["case_id"], "kyc-uae")
    assert recovered["status"] == "awaiting_review"
    assert recovered["interrupt"]["type"] == "review"
    done = r2.resume(case["case_id"], {"action": "approve", "note": "post-restart"})
    assert done["status"] == "approved"
```

- [ ] **Step 2: Implement `CaseRunner.recover_case`** in `src/voxgate/service/runner.py`

```python
    def recover_case(self, case_id, pack_id):
        """Rehydrate the store entry for a case that exists only in the checkpointer."""
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": {}})
        return self._sync(case_id, pack_id)
```

Also add a `list_known_threads` note: full store rebuild on boot is a Plan 3 concern (the dashboard needs it); for now `recover_case` is the explicit per-case recovery path and the integration test its consumer.

- [ ] **Step 3: Run the integration test**

Run: `docker compose up -d; $env:VOXGATE_TEST_DB="postgresql://voxgate:voxgate@localhost:5433/voxgate"; uv run pytest tests/integration -v`
Expected: 1 PASS (and SKIP when the env var is absent: `uv run pytest tests/integration -v` in a fresh shell)

- [ ] **Step 4: Write `scripts/demo_case.py`** — CLI demo against a running server (`uv run uvicorn voxgate.service.app:app`). Uses httpx; no arguments = clean applicant, `--risky` = sanctions-lookalike applicant. It must: create a case, print the interview interrupt payload, submit the scripted fields as the "interview", pretty-print check results + the score waterfall (feature name, value, weight, contribution, one `#`-bar per 0.1 contribution), and if the case parks at review, prompt `approve/reject/request_info` on stdin and submit the decision. ~80 lines; print every status transition with the case id so a screen recording of this is the Plan-1 demo artifact.

- [ ] **Step 5: Manual end-to-end check**

Run (terminal 1): `uv run uvicorn voxgate.service.app:app --port 8000`
Run (terminal 2): `uv run python scripts/demo_case.py --risky`
Expected: case parks at `awaiting_review` with a printed score waterfall showing `sanctions_similarity` dominating; typing `approve` finishes the case. Then restart terminal 1 mid-review (with `VOXGATE_DATABASE_URL` set) and confirm the decision still lands after restart.

- [ ] **Step 6: Write `README.md`, `.paul/PROJECT.md`, `.paul/STATE.md`**

`README.md`: what VoxGate is (3 sentences), quickstart (uv sync → docker compose up → uvicorn → demo script), test matrix (`uv run pytest` / integration env var), pack-authoring guide (the module contract from Task 4, ~15 lines), and the 4-plan roadmap. `.paul/PROJECT.md`: goal, architecture summary, spec + plan links. `.paul/STATE.md`: Plan 1 complete, Plans 2–4 pending, date 2026-08-06.

- [ ] **Step 7: Final full regression**

Run: `uv run pytest -v`
Expected: all green (integration tests skip without the env var — that's fine)

---

