# VoxGate — Research Notes

Findings from the 2026-08-07 research session. Each file is a verbatim-faithful record
of one research pass, written so a future session (or a subagent) can act on it without
redoing the work.

**Everything here was verified against live sources on 2026-08-07** — installed package
source in `.venv`, PyPI/GitHub release APIs, live docs, and live site inspection. Where a
source disagreed with published documentation, the note says so. Nothing here is recalled
from model memory.

| File | Topic | Status |
|---|---|---|
| [`2026-08-07-pipecat-integration.md`](2026-08-07-pipecat-integration.md) | Pipecat 1.7.0 — architecture, local zero-key services, RTVI, WebRTC, integration pattern | Complete |
| [`2026-08-07-frontend-techniques.md`](2026-08-07-frontend-techniques.md) | Awwwards 2026 technique + tooling survey, filtered for a dense ops console | Complete |
| [`2026-08-07-dashboard-asset-inventory.md`](2026-08-07-dashboard-asset-inventory.md) | Exact inventory of the half-built dashboard: tokens, classes, IDs, gap analysis | Complete |
| [`2026-08-07-skills-inventory.md`](2026-08-07-skills-inventory.md) | Which local agent skills apply to this project and when to invoke them | Complete |
| [`2026-08-07-langgraph-production-upgrade.md`](2026-08-07-langgraph-production-upgrade.md) | LangGraph 1.x production/multi-tenant upgrade design | See file |

## How to read these

The notes are deliberately long. They are reference material, not a plan. The plan that
acts on them is [`../ROADMAP.md`](../ROADMAP.md), which cites back into these files.

## Standing corrections these notes establish

Three findings invalidate assumptions baked into existing project docs. They are repeated
here because they are easy to miss inside long files:

1. **`PipelineTask` / `PipelineRunner` are deprecated** (since Pipecat 1.3.0, removed in
   2.0.0). Use `PipelineWorker` / `WorkerRunner`. `docs/design/2026-08-06-voice-agent-plan2-design.md`
   §4 task 6 targets the dead API.

   **Related, verified by cloning the repo:** `TransportParams` has no `vad_analyzer`.
   For an LLM-free pipeline like ours, VAD goes in a standalone `VADProcessor` plus a
   `UserTurnProcessor`. See the box at the top of the Pipecat note.
2. **RTVI is enabled by default** and already carries transcripts, speaking state, and
   audio levels. The custom `caption` WebSocket event invented in that same design doc
   §3.3 should be deleted rather than built.
3. **Local STT is segmented, not streaming** — there are no true interim transcripts from
   `WhisperSTTService`. The "word-by-word captions" in the dashboard spec cannot be built
   as described against local Whisper.
