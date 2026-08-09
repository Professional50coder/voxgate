## Global Constraints

- **No git in this folder** (user request). Every task ends at green tests — skip any commit habit. Do NOT run `git init` or any `git` command.
- Dev machine is **Windows 11 / PowerShell** — all `Run:` commands are PowerShell-compatible; always invoke tools through `uv run …` from the repo root `C:\Users\GAURAV\OneDrive\Desktop\PPC_Tech\voxgate`.
- **Zero paid keys** in this plan: no LLM, STT, or TTS calls anywhere. The sync graph is used everywhere (`.invoke`/`.get_state`, never the async variants) so tests need no asyncio plumbing.
- All datasets are **mock/synthetic** and every dataset file carries `"synthetic": true` at its top level.
- Scorecard routing thresholds come from `pack.yaml` (`kyc-uae`: low `0.30`, high `0.65`); never hard-code them in platform code.
- Re-ask loop is capped at **2** (`MAX_REASKS = 2` in `graph/build.py`); after the cap, cases go to the reviewer gate.
- Status vocabulary (exact strings, used by store, API, and tests): `awaiting_interview`, `processing`, `awaiting_review`, `approved`, `rejected`, `needs_attention`.
- Embeddings are optional everywhere: `NameMatcher(embedder=None)` must work (weights renormalize) — sentence-transformers is an optional extra, never imported at module top level.

---
