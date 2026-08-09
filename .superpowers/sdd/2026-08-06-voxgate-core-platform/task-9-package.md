# Task 9 review package - full contents of created/changed files (README.md included whole; only the Pack authoring + roadmap sections are new)

=== FILE: tests/integration/test_postgres_resume.py ===
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


=== FILE: src/voxgate/service/runner.py ===
import uuid
from langgraph.types import Command

class CaseRunner:
    def __init__(self, packs, checkpointer_factory, store, bus):
        self.packs, self.store, self.bus = packs, store, bus
        checkpointer = checkpointer_factory()
        from voxgate.graph.build import build_graph
        self.graphs = {pid: build_graph(p, checkpointer) for pid, p in packs.items()}

    def _cfg(self, case_id):
        return {"configurable": {"thread_id": case_id}}

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
                "interrupt": pending}
        self.store.upsert(case)
        self.bus.publish(case_id, {"kind": "state", "case": self.store.get(case_id)})
        return self.store.get(case_id)

    def _mark_needs_attention(self, case_id, pack_id, e):
        self.store.upsert({"case_id": case_id, "pack_id": pack_id,
                           "status": "needs_attention", "error": str(e)})
        self.bus.publish(case_id, {"kind": "state", "case": self.store.get(case_id)})
        return self.store.get(case_id)

    def start_case(self, pack_id):
        case_id = str(uuid.uuid4())
        self.store.upsert({"case_id": case_id, "pack_id": pack_id,
                           "status": "awaiting_interview", "live_fields": {}})
        try:
            self.graphs[pack_id].invoke(
                {"case_id": case_id, "pack_id": pack_id, "reask_count": 0}, self._cfg(case_id))
        except Exception as e:
            return self._mark_needs_attention(case_id, pack_id, e)
        return self._sync(case_id, pack_id)

    def _pack_of(self, case_id):
        case = self.store.get(case_id)
        if case is None:
            raise KeyError(case_id)
        return case["pack_id"]

    def resume(self, case_id, payload):
        pack_id = self._pack_of(case_id)
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
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": {}})
        return self._sync(case_id, pack_id)

    def patch_fields(self, case_id, fields, confidence):
        pack_id = self._pack_of(case_id)
        case = self.store.get(case_id)
        live = {**case.get("live_fields", {}), **fields}
        self.store.upsert({"case_id": case_id, "pack_id": pack_id, "live_fields": live})
        self.bus.publish(case_id, {"kind": "fields", "fields": live, "confidence": confidence})
        return self.store.get(case_id)


=== FILE: scripts/demo_case.py ===
"""VoxGate CLI demo — drives one kyc-uae case end-to-end against a running server.

Terminal 1: uv run uvicorn voxgate.service.app:app --port 8000
Terminal 2: uv run python scripts/demo_case.py            # clean applicant, auto-approves
            uv run python scripts/demo_case.py --risky     # sanctions-lookalike, parks for review

This is the Plan-1 demo artifact: run it while screen-recording to show a case
being created, interviewed, scored, and (for --risky) reviewed by a human.
"""
import argparse
import httpx

BASE = "http://127.0.0.1:8000"

CLEAN = {"full_name": "Priya Raghavan", "dob": "1992-04-15", "nationality": "IN",
         "residency_status": "uae_resident", "source_of_funds": "salary",
         "product": "spot_trading"}
RISKY = {"full_name": "Muhammad Al-Rashid", "dob": "1975-03-02", "nationality": "SY",
         "residency_status": "non_resident", "source_of_funds": "crypto_trading",
         "product": "derivatives"}


def transition(case):
    print(f"[{case['case_id']}] status={case['status']}")


def print_waterfall(score):
    print(f"  probability={score['probability']:.4f}  band={score['band']}")
    for c in sorted(score["contributions"], key=lambda c: -abs(c["contribution"])):
        bars = "#" * round(abs(c["contribution"]) / 0.1)
        print(f"  {c['feature']:<24} value={c['value']:<7} weight={c['weight']:<5} "
              f"contribution={c['contribution']:+.4f} {bars}")


def print_checks(check_results):
    for c in check_results:
        print(f"  check={c['check_name']:<14} status={c['status']:<7} score={c['score']:.3f}")


def main():
    parser = argparse.ArgumentParser(description="VoxGate demo CLI")
    parser.add_argument("--risky", action="store_true", help="use the sanctions-lookalike applicant")
    args = parser.parse_args()
    fields = RISKY if args.risky else CLEAN

    client = httpx.Client(base_url=BASE, timeout=10.0)

    case = client.post("/cases", json={"pack_id": "kyc-uae"}).json()
    transition(case)
    print("interview interrupt payload:")
    print(f"  reask_fields={case['interrupt']['reask_fields']}  fields_so_far={case['interrupt']['fields_so_far']}")

    print(f"[{case['case_id']}] submitting interview fields ({'RISKY' if args.risky else 'CLEAN'})")
    case = client.post(f"/cases/{case['case_id']}/interview-result",
                       json={"fields": fields, "confidence": {}}).json()
    transition(case)

    if case.get("check_results"):
        print("check results:")
        print_checks(case["check_results"])
    if case.get("score"):
        print("score waterfall:")
        print_waterfall(case["score"])

    if case["status"] == "awaiting_review":
        print(f"[{case['case_id']}] parked for human review - gate_role={case['interrupt']['gate_role']}")
        action = ""
        while action not in {"approve", "reject", "request_info"}:
            action = input("decision (approve/reject/request_info): ").strip().lower()
        note = input("note (optional): ").strip()
        case = client.post(f"/cases/{case['case_id']}/decision",
                           json={"action": action, "note": note}).json()
        transition(case)

        if case["status"] == "processing":  # request_info re-opened the interview
            print(f"[{case['case_id']}] re-interview requested — resubmitting fields")
            case = client.post(f"/cases/{case['case_id']}/interview-result",
                               json={"fields": fields, "confidence": {}}).json()
            transition(case)

    print(f"[{case['case_id']}] final status: {case['status']}")


if __name__ == "__main__":
    main()


=== FILE: README.md ===
# VoxGate

VoxGate is a pack-driven voice-interview compliance gating platform: a durable, human-in-the-loop case workflow (LangGraph) that pairs explainable AI/ML scoring (fuzzy/embedding name matching, additive log-odds scorecards) with a scenario-pack system so a new compliance/onboarding use case can be added without touching platform code. v1 ships one pack, `kyc-uae` — UAE fintech KYC onboarding with sanctions/PEP/adverse-media screening.

This README covers the backend core (config, ML, pack loader, graph, service). For phase-by-phase build detail see [`docs/phases/README.md`](docs/phases/README.md); for architecture/status see [`.paul/PROJECT.md`](.paul/PROJECT.md) and [`.paul/STATE.md`](.paul/STATE.md).

## Prerequisites

- **Python 3.12+**
- **uv** (Python package/project manager) — install one-liners below are the official commands per [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/):

  Windows (PowerShell):
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  macOS / Linux:
  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  If either command has changed, the current instructions are always at <https://docs.astral.sh/uv/>.

No other tools are required. No paid API keys are required to run the test suite.

## Setup on any device

```sh
git clone <this-repo-url> voxgate   # or copy the folder
cd voxgate
uv sync
uv run pytest -q
```

That's it — **no path edits, no hardcoded machine-specific paths anywhere.** `src/voxgate/config.py` derives the repo root from its own file location (`REPO_ROOT = Path(__file__).resolve().parents[2]`), so `Settings.packs_dir` defaults to `<repo_root>/packs` correctly regardless of which drive, user account, or OS the repo lives on, and regardless of the working directory `uv run` is invoked from.

Everything is overridable via environment variables (prefix `VOXGATE_`) or a `.env` file — copy `.env.example` to `.env` and edit as needed:

- `VOXGATE_DATABASE_URL` — Postgres DSN; unset (default) runs fully in-memory, no database needed.
- `VOXGATE_PACKS_DIR` — override where scenario packs are loaded from.

## Dependency policy

- **`pyproject.toml`** declares dependency *ranges* (`>=`) — the latest-compatible versions at install time.
- **`uv.lock`** (and its exported `requirements.txt`) is the **tested, pinned snapshot** used for reproducible installs — `uv sync` installs exactly what's in `uv.lock`, not just "whatever satisfies the ranges today."
- **`requirements.txt` is autogenerated** via `uv export` — never hand-edit it; regenerate it from `uv.lock` if it needs to change.
- **To move to the latest compatible versions:**
  ```sh
  uv lock --upgrade
  uv sync
  uv run pytest -q
  ```
  Only keep the upgrade if the full suite still passes.

## Project layout

```
src/voxgate/
  config.py        # Settings — DB DSN, packs_dir (repo-root-relative, never hardcoded)
  ml/               # variants.py, name_match.py, scorecard.py — pack-agnostic ML primitives
  packs/            # base.py (Pack/CheckResult contract), loader.py (dynamic pack loading)
  graph/            # LangGraph case state machine (state.py, build.py)
  service/          # CaseStore, EventBus, CaseRunner, FastAPI app
packs/kyc_uae/       # the kyc-uae scenario pack: pack.yaml, schema.py, checks.py, scoring.py, data/
tests/               # pytest suite, one file per module/phase; pack_conformance.py is the shared
                     # contract suite every pack must pass; tests/integration/ is Postgres-gated
docs/phases/         # one detailed doc per build phase, README.md indexes all of them
.paul/               # PROJECT.md (architecture/goal), STATE.md (build status)
```

## Running tests

```sh
uv run pytest -q                       # full fast suite — no external services required
uv run pytest tests/test_config.py -v          # Settings
uv run pytest tests/test_name_match.py -v      # name-matching ensemble
uv run pytest tests/test_scorecard.py -v       # scorecard engine
uv run pytest tests/test_pack_loader.py -v     # pack loader
uv run pytest tests/test_pack_kyc_uae.py -v    # kyc-uae pack + conformance
```

Postgres-backed integration tests are opt-in and skip cleanly without a database:

```sh
docker compose up -d
```
```sh
# PowerShell
$env:VOXGATE_TEST_DB = "postgresql://voxgate:voxgate@localhost:5433/voxgate"
```
```sh
# macOS/Linux
export VOXGATE_TEST_DB="postgresql://voxgate:voxgate@localhost:5433/voxgate"
```
```sh
uv run pytest tests/integration -v
```

## Platform notes

- Every path in the codebase is built with `pathlib.Path`, not string concatenation or OS-specific separators — this is what makes the project run unmodified on Windows, macOS, and Linux.
- **One honest caveat:** `config.py`'s repo-root derivation (`Path(__file__).resolve().parents[2]`) assumes an editable/source checkout — the layout `uv sync` produces by default (this repo, run in place). If the `voxgate` package were ever built into a wheel and `pip install`-ed into `site-packages` on some other machine, `parents[2]` would resolve to a location with no `packs/` directory alongside it. In that deployment shape, set `VOXGATE_PACKS_DIR` explicitly (env var or `.env`) rather than relying on the default.

## Pack authoring

A scenario pack is a directory under `packs/<pack_id>/` exposing a fixed module contract (`src/voxgate/packs/loader.py`); platform code never imports a pack by name, so adding one needs zero platform-code changes — enforced by `tests/pack_conformance.py`.

- **`pack.yaml`** — `pack_id`, `display_name`, `gate_role`, `thresholds: {low, high}` (scorecard routing bands).
- **`schema.py`** — a Pydantic `Schema` model (interview fields + plausibility validators) and `REASK_HINTS: dict[field, prompt]`, used to re-ask a field that fails validation.
- **`checks.py`** — `CHECKS: list[Callable[[dict], CheckResult]]`; each takes validated fields and returns a `CheckResult` (`check_name`, `status`: `clear`/`review`/`hit`, `score`, `details`).
- **`scoring.py`** — `build_scorecard(low, high) -> Scorecard` (additive log-odds features over fields/checks) and `FEATURE_FIELD_HINTS: dict[feature, field]`, used to pick the re-ask field for a medium-band case.
- **`prompt.md`** — the interview system prompt (consumed by the Plan 2 voice bot).

See `packs/kyc_uae/` for a working example and `tests/test_pack_kyc_uae.py` for the contract exercised end-to-end.

## Roadmap

1. **Plan 1 — Core platform (this repo).** Pack system, LangGraph case state machine, FastAPI service, Postgres durability, demo CLI. Complete.
2. **Plan 2 — Voice bot.** Pipecat (WebRTC → STT → LLM → TTS) drives the interview interrupt over the same REST surface.
3. **Plan 3 — Dashboard.** React reviewer UI (case queue, risk waterfall, WS live updates), plus the `CaseStore` rebuild-on-boot (`list_known_threads`) it needs.
4. **Plan 4 — Hardening.** Auth/multi-tenancy, production deployment, `realestate-aml` / `patient-intake` packs.

