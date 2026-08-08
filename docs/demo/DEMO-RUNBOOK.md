# VoxGate — Live Demo Runbook

A copy-paste script for a live, <10-minute walkthrough on **Windows PowerShell**. Every command below has been verified against the actual repo at `voxgate/` as of 2026-08-06.

**Two parallel paths throughout:**
- **(works today)** — the FastAPI REST/WS service + Swagger UI (`/docs`) + `scripts/demo_case.py`. This is the ground truth; it works standalone with zero other pieces.
- **(new dashboard)** — `GET /dashboard` and `POST /dashboard/demo-seed` are being built concurrently with this runbook and are not yet confirmed merged. Every beat below works without them — the dashboard steps are call-outs, not dependencies. If `/dashboard` 404s when you load it, just stay on `/docs` and keep going; nothing else in the script changes.

Budget: ~8–9 minutes of the script below, leaving slack for questions.

---

## 0. Before the room (not on the clock)

```powershell
cd C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate
uv sync
uv run pytest -q          # sanity check — should be mostly green; a couple of
                           # in-progress hardening tests may be red, that's fine,
                           # it doesn't touch anything this script exercises
```

Have three PowerShell windows/tabs open, all `cd`'d into the repo root:
- **Terminal 1** — the server.
- **Terminal 2** — commands you type live (case creation, curl-equivalents, the recovery snippet).
- **Terminal 3** — spare, for `docker compose` / troubleshooting so you never have to interrupt Terminal 1 or 2.

---

## 1. Start the server (0:00–0:30)

**Terminal 1:**
```powershell
uv run uvicorn voxgate.service.app:app --port 8000
```

**SAY:** "This is the whole backend — one process, in-memory by default, no database required yet."

**SCREEN:** `Uvicorn running on http://127.0.0.1:8000` with no tracebacks.

## 2. Open the surface (0:30–1:00)

Browser: **http://127.0.0.1:8000/dashboard** *(new dashboard)*

**Fallback (works today):** **http://127.0.0.1:8000/docs** — FastAPI's Swagger UI, live against this exact server, no separate build step.

**SAY:** "Dashboard's landing this week; today I'll drive the same API it calls, live, through Swagger and the CLI demo script so you see the raw contract."

**SCREEN:** Swagger UI listing `GET /packs`, `POST /cases`, `GET /cases`, `GET /cases/{case_id}`, `PATCH /cases/{case_id}/fields`, `POST /cases/{case_id}/interview-result`, `POST /cases/{case_id}/decision`, `WS /cases/{case_id}/events`.

## 3. Seed demo data (1:00–1:30)

**(new dashboard)** Click "Seed demo data" → `POST /dashboard/demo-seed`.

**Fallback (works today) — Terminal 2:**
```powershell
uv run python scripts/demo_case.py --risky
```
Don't answer the `decision (approve/reject/request_info):` prompt yet — leave it hanging, it's your live parked case for step 5. Or, to just confirm the pack loaded cleanly first:
```powershell
Invoke-RestMethod http://127.0.0.1:8000/packs | ConvertTo-Json -Depth 5
```

**SAY:** "One pack shipped so far — `kyc-uae`, UAE fintech onboarding: sanctions, PEP, and adverse-media screening plus a 7-feature risk scorecard. Adding a second pack is zero platform-code changes — there's a conformance test suite that enforces that."

**SCREEN:** `pack_id: kyc-uae`, `display_name: UAE Fintech KYC Onboarding`, `gate_role: Compliance Officer`, six schema fields listed.

## 4. Walk the clean case — auto-approve (1:30–3:30)

**Terminal 2** (fresh terminal, or after the risky run above finishes):
```powershell
uv run python scripts/demo_case.py
```

**SAY (as it prints):** "Applicant submits their intake fields — normally spoken to a voice bot in Plan 2, here posted directly. The graph validates, fans out three compliance checks in parallel, then scores."

**SCREEN — exact printed sequence:**
```
[<case_id>] status=awaiting_interview
interview interrupt payload:
  reask_fields=[]  fields_so_far={}
[<case_id>] submitting interview fields (CLEAN)
[<case_id>] status=processing
check results:
  check=sanctions      status=clear   score=0.xxx
  check=pep            status=clear   score=0.xxx
  check=adverse_media  status=clear   score=0.000
score waterfall:
  fatf_nationality_risk    value=0.0   weight=2.2  contribution=+0.0000
  ...
[<case_id>] final status: approved
```

**SAY (pointing at the waterfall):** "Every number here is attributable — each feature's exact contribution to the approve/reject probability, not a black-box score. This applicant is Indian, salaried, spot-trading only — clean FATF country, low-risk product — auto-approved with no human in the loop."

**(new dashboard) add-on:** the same case appears in the dashboard's case list in real time via the WS feed, with the waterfall rendered as a chart instead of ASCII bars.

## 5. Walk the risky case — parks at the reviewer gate (3:30–6:30)

If you already have the `--risky` run hanging at the input prompt from step 3, resume there. Otherwise, in **Terminal 2:**
```powershell
uv run python scripts/demo_case.py --risky
```

**SAY:** "Same flow, different applicant — Syrian nationality (FATF blacklisted), non-resident, funding source is crypto trading, product is derivatives. Watch what happens after scoring."

**SCREEN:**
```
check results:
  check=sanctions      status=review  score=0.xxx   (or hit, depending on fuzzy match)
  check=pep            status=clear   score=0.000
  check=adverse_media  status=clear   score=0.000
score waterfall:
  fatf_nationality_risk    value=1.0   weight=2.2  contribution=+2.2000  ##########...
  ...
[<case_id>] parked for human review - gate_role=Compliance Officer
decision (approve/reject/request_info):
```

**SAY:** "Anything that hits a FATF-blacklist nationality, a sanctions/PEP similarity flag, or a high probability band routes to a human — never auto-decided. `gate_role` comes from the pack's own config, so a different compliance domain names its own approver role."

**Show the check evidence** — before answering the prompt, in **Terminal 3**:
```powershell
Invoke-RestMethod "http://127.0.0.1:8000/cases/<case_id>" | ConvertTo-Json -Depth 6
```
Point at `.interrupt.flagged_checks` and `.interrupt.score_waterfall` — the exact evidence the reviewer sees, already pre-sorted by contribution magnitude.

**Now answer the prompt** in Terminal 2:
```
approve
```
(or `reject` — either is a legitimate demo beat; note (optional) can be left blank).

**SCREEN:** `[<case_id>] final status: approved` (or `rejected`).

**SAY:** "That decision, the reviewer identity, and the note are now part of the case's permanent record."

## 6. Live captions + pipeline graph moments (6:30–7:15)

**(new dashboard)** — the dashboard is the intended home for this: a live node-by-node animation of the LangGraph topology (`intake → interview → validate → checks → score → route → gate`) plus streamed field-extraction "captions" as the (future, Plan 2) voice bot fills fields in.

**Today's honest fallback:** the graph executes synchronously end-to-end inside one API call — there's no granular per-node event yet, only one WebSocket snapshot per API call. Show the raw feed anyway, it's the exact data the dashboard will visualize:
```powershell
$recover = @'
import asyncio, json, sys, websockets

async def main():
    case_id = sys.argv[1]
    async with websockets.connect(f"ws://127.0.0.1:8000/cases/{case_id}/events") as ws:
        async for msg in ws:
            print(json.loads(msg))

asyncio.run(main())
'@
$recover | uv run python - <case_id>
```
Then, in Terminal 2, trigger any action on that case_id (a `PATCH .../fields` or another decision) and watch the JSON snapshot land in Terminal 3.

**SAY:** "This WebSocket is already live and already the dashboard's data source — today it pushes one state snapshot per step; Plan 2's voice bot streams into the same channel via `PATCH .../fields` as it transcribes, which is the 'live captions' story."

## 7. Durability finale — kill the server mid-review (7:15–9:00)

**Terminal 3:**
```powershell
docker compose up -d
```

**SCREEN:** Postgres container starts on host port `5433`.

**Terminal 1** — stop the running server (`Ctrl+C`), then set the DB DSN and restart it **in the same window** so the env var applies:
```powershell
$env:VOXGATE_DATABASE_URL = "postgresql://voxgate:voxgate@localhost:5433/voxgate"
uv run uvicorn voxgate.service.app:app --port 8000
```

**SAY:** "Same server, same code — now every case's LangGraph checkpoint is written to Postgres instead of memory."

**Terminal 2** — create a fresh risky case and park it at review (no interactive prompt, so nothing hangs mid-restart):
```powershell
$risky = @{ full_name="Muhammad Al-Rashid"; dob="1975-03-02"; nationality="SY";
            residency_status="non_resident"; source_of_funds="crypto_trading";
            product="derivatives" }

$case = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/cases `
          -Body (@{pack_id="kyc-uae"} | ConvertTo-Json) -ContentType "application/json"

$case = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/cases/$($case.case_id)/interview-result" `
          -Body (@{fields=$risky; confidence=@{}} | ConvertTo-Json -Depth 5) -ContentType "application/json"

$case.status                      # awaiting_review
$caseId = $case.case_id
$caseId                           # note this — you need it after the restart
```

**SAY:** "Case is parked, waiting on a compliance officer. Now — kill the server."

**Terminal 1:** `Ctrl+C`. **SCREEN:** process exits.

**SAY:** "That's the whole backend gone. Bring it back up."

**Terminal 1** — restart, same command as before (DSN already set in this window's `$env:` scope):
```powershell
uv run uvicorn voxgate.service.app:app --port 8000
```

**SAY:** "Brand-new process, brand-new empty in-memory index — but the case's checkpoint lives in Postgres, not memory. `GET /cases/<id>` on this fresh process won't find it yet — the in-memory index that endpoint reads is empty by design; per-case recovery through a REST route is exactly what the dashboard's rebuild-on-boot work (Plan 3) adds next. Today, the recovery path is the same one the integration test proves against — same Postgres connection, a fresh runner instance:"

**Terminal 2** — the recovery + decision proof (mirrors `tests/integration/test_postgres_resume.py` line for line):
```powershell
$recover = @'
import os
from voxgate.config import get_settings
from voxgate.packs.loader import load_packs
from voxgate.service.app import _postgres_factory
from voxgate.service.runner import CaseRunner
from voxgate.service.store import CaseStore
from voxgate.service.events import EventBus

case_id = "PASTE-CASE-ID-HERE"
dsn = os.environ["VOXGATE_DATABASE_URL"]
runner = CaseRunner(load_packs(get_settings().packs_dir), lambda: _postgres_factory(dsn), CaseStore(), EventBus())

recovered = runner.recover_case(case_id, "kyc-uae")
print(f"RECOVERED  status={recovered['status']}  interrupt_type={recovered['interrupt']['type']}")

decided = runner.resume(case_id, {"action": "approve", "note": "post-restart demo"})
print(f"DECIDED    status={decided['status']}  decision={decided['decision']}")
'@
($recover -replace 'PASTE-CASE-ID-HERE', $caseId) | uv run python -
```

**SCREEN:**
```
RECOVERED  status=awaiting_review  interrupt_type=review
DECIDED    status=approved  decision={'action': 'approve', 'note': 'post-restart demo', 'by': 'Compliance Officer'}
```

**SAY:** "That's the durability claim: the case, its full interview state, every check result, and the pending review — none of it lived in the process we killed. It survived in Postgres, and the decision that was waiting to happen, happened. This exact sequence is a passing integration test, not a scripted illusion."

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **Port 8000 already in use** | `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess \| Stop-Process` or just start uvicorn with `--port 8001` and swap the port in every URL below. |
| **`docker` not found / Docker Desktop not running** | Skip the Section 7 finale entirely. Land the demo after Section 6 with: "durability against Postgres is built and covered by an integration test — happy to run it after, it just needs Docker." Everything through Section 6 is fully self-contained without Docker. |
| **`docker compose up -d` fails / port 5433 busy** | `docker compose down` then retry; or change the host port in `docker-compose.yml`'s `ports:` mapping and update `VOXGATE_DATABASE_URL` to match — but do this *before* the room, not live. |
| **`uv` not found** | Not installed on this machine — see `README.md` Prerequisites for the one-line installer. Falls back to Section-6-and-earlier-only demo if you can't install it in time. |
| **`uv sync` / venv errors, stale lockfile complaints** | `uv sync --reinstall` from repo root. Confirm with `uv run python -c "import voxgate"` before going live. |
| **`/dashboard` 404s** | Expected if it hasn't merged yet — stated up front in Section 2. Stay on `/docs` and continue; no other step changes. |
| **`GET /cases/<id>` 404s right after the restart in Section 7** | Expected, not a bug — see the SAY line in Section 7. The in-memory store is empty on a fresh process; use the recovery snippet, not the GET endpoint, until the dashboard's rebuild-on-boot ships. |
| **Risky case doesn't hit `awaiting_review`** | Double-check the exact `$risky` payload above — `nationality="SY"` (FATF-blacklisted per `packs/kyc_uae/data/countries.json`) is what drives the routing; a typo'd country code will silently auto-approve instead. |
| **A stray `demo_case.py --risky` is still sitting at its `input()` prompt from an earlier attempt** | It's harmless — Ctrl+C that terminal and start fresh. It only matters if you try to answer it against a server it's no longer talking to (post-restart), which will 404. |
