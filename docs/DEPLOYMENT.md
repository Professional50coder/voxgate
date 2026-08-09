# Deploying VoxGate

## Deploying on Vercel

VoxGate is two separate Vercel projects in one repository:

1. **API** — root directory is the repo root. Vercel detects Python/FastAPI from
   `pyproject.toml`; `tool.vercel.entrypoint = "app:app"` points the build at
   the top-level FastAPI instance in `app.py`.
2. **Web app** — subject path `apps/web`. Vercel detects Next.js from that
   directory's `package.json`. Set its `API_ORIGIN` env var to the API
   project's URL so `/api/*` rewrites reach the backend. See
   `apps/web/README.md`.

The browser talks only to the web app's origin; `next.config.ts` proxies
`/api/*` to the API, so CORS is never involved.

Two processes and a Postgres database. The frontend proxies to the API, so the
browser only ever talks to one origin.

```
browser ──▶ Next.js (apps/web)  ──/api/*──▶  FastAPI (uvicorn)  ──▶  Postgres
```

---

## 1. Postgres

Any Postgres 14+ works: a managed instance, Neon, Supabase, or one you run.
The schema is created on start, so there is nothing to run by hand.

Take the **pooled** connection string if your provider offers one. The pools are
already configured for a transaction pooler (`autocommit=True`,
`prepare_threshold=0`), which is required for pgbouncer and Neon's pooled
endpoint and harmless on a direct connection.

```
postgresql://USER:PASSWORD@HOST:5432/DBNAME
```

## 2. The API

```bash
uv sync                       # or: pip install -r requirements.txt
uv run uvicorn voxgate.service.app:app --host 0.0.0.0 --port 8000
```

Environment:

| Variable | Required | What it does |
|---|---|---|
| `VOXGATE_DATABASE_URL` | **yes in production** | Postgres DSN. Unset means in-memory: every case is lost on restart, and more than one worker is unsafe. |
| `GROQ_API_KEY` | for LLM features | Field extraction and pack drafting. Without it they fall back to keyword matching, which is much weaker. |
| `GROQ_API_KEYS` | no | Comma-separated extra keys. Groq rate-limits per key **and** per model, so N keys × M models is the real headroom. |
| `EXA_API_KEY` | no | Research enrichment. |
| `VOXGATE_API_KEYS` | **yes in production** | Comma-separated operator keys. Unset means the case board, reviewer decisions and pack publishing are open to anyone. Several keys are accepted so you can rotate without downtime. |
| `VOXGATE_CORS_ORIGINS` | only if not proxying | Comma-separated browser origins. Not needed with the Next.js proxy below, because the browser sees one origin. |
| `VOXGATE_PACKS_DIR` | no | Defaults to `packs/` in the repo. See "Packs are files" below. |

### Workers

More than one worker **requires** `VOXGATE_DATABASE_URL`. With it set, the event
bus and the case store are both in Postgres and a request may be served by any
worker. Without it, both are per-process: a browser holding a live view on
worker B never sees an update published by worker A, and the stream goes quiet
with no error at either end.

```bash
uvicorn voxgate.service.app:app --host 0.0.0.0 --port 8000 --workers 4
```

**On Windows, `--workers` does not work** — uvicorn cannot share a listen socket
across processes there, and workers past the first fail to bind with
`WinError 10022`. This is a platform limitation, not a configuration mistake.
Deploy on Linux, or run several single-worker processes on different ports
behind a load balancer, which is what was used to verify the cross-process
guarantee here.

### Packs are files

A pack is a directory of Python under `packs/`, and publishing writes a new one
at runtime. Two consequences for hosting:

- **The packs directory must be writable and shared by every worker.** On one
  box that is automatic. Across boxes it needs shared storage, or you accept
  that a pack published on one machine is invisible to the others.
- **A container with an ephemeral filesystem loses published packs on redeploy.**
  Mount a volume at the packs directory, or treat published packs as drafts and
  commit the ones you want to keep.

## 3. The frontend

```bash
cd apps/web
npm ci
npm run build
API_ORIGIN=http://your-api-host:8000 npm start
```

`API_ORIGIN` is read **server-side at start**, not baked into the bundle at
build time. That distinction matters: a `NEXT_PUBLIC_` variable is inlined into
the JavaScript every visitor downloads, so a build made on a laptop would ship a
bundle telling every visitor's browser to call *their own* machine. Do not
reintroduce one.

`next.config.ts` rewrites `/api/*` to `API_ORIGIN`, so the browser makes
same-origin requests and CORS never enters the picture.

**If you cannot proxy** — a static CDN, say — set `NEXT_PUBLIC_API_URL` to the
API's public URL at build time and set `VOXGATE_CORS_ORIGINS` on the API to the
frontend's origin. Scheme and port must match exactly;
`https://app.example.com` and `http://app.example.com` are different origins to
a browser.

## 4. The voice worker (optional)

A separate process, because it holds Whisper and Kokoro in memory and making
every API worker carry those would multiply the footprint of a service that
mostly serves JSON.

```bash
uv sync --extra voice          # heavy: torch, transformers, model downloads
uv run --extra voice python -m voxgate.voice --pack-id kyc-uae
```

It opens a case, listens on `ws://0.0.0.0:8765` for raw audio, and drives the
interview:

```
transport.input -> Whisper -> InterviewProcessor -> Kokoro -> transport.output
```

**There is no language model in that loop.** The questions come from the pack's
own `reask_hints`, so a regulated question is asked in the wording the pack
defines rather than a paraphrase invented at runtime. A model is used for one
bounded job -- mapping a spoken sentence onto the value the schema requires --
and its output is validated against the pack's allowed values before it is
accepted, so a wrong answer there is a re-ask and never a wrong decision.

Everything runs locally by default. An applicant's voice is biometric data, and
in an identity interview it is attached to their name and date of birth, so it
does not leave the machine unless you opt into a hosted service.

## 5. Behind a reverse proxy

The API must receive WebSocket upgrades for `/cases/{id}/events`, and the live
view is the product's whole point.

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade    $http_upgrade;     # required for the live view
    proxy_set_header Connection "upgrade";
    proxy_set_header Host       $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 3600s;                      # sockets are long-lived
}
```

`X-Forwarded-For` matters: without it the rate limiter sees every request as
coming from the proxy and limits all clients as one.

## 6. Health checks

| Path | Use it for |
|---|---|
| `GET /health` | Liveness. Dependency-free. If it fails, restart the process. |
| `GET /health/ready` | Readiness. Reports Postgres, pack count, and whether auth is enabled. Returns 503 when not ready — pull the instance out of rotation rather than restarting it. |

Point your load balancer at `/health/ready` and your restart policy at
`/health`. Using one for both means a database blip restarts every instance you
have, which is the opposite of what you want.

---

## Before this is public

**Set `VOXGATE_API_KEYS`.** Without it the operator endpoints are open, which
`/health/ready` reports (`auth: "disabled"`) and the log warns about at startup.
With it set, the case board, reviewer decisions, pack drafting and
`POST /packs/publish` require the key; the applicant interview does not, and
never will.

> `POST /packs/publish` writes generated Python to the server and imports it.
> Every value reaching generated source is type-checked or escaped, with
> regression tests for the two injections that were possible before -- but it is
> also behind the operator key now, which is the layer you actually want if one
> of those escapes is ever wrong again.

Still outstanding:

- **A case UUID is a bearer capability.** `GET /cases/{id}` is deliberately open,
  because that is what an invite link is. Anyone holding the link can read that
  one case, so treat case ids as secrets -- they are v4 UUIDs for this reason.
  `GET /cases`, the whole board, is protected.
- **Tenancy is schema-ready but not enforced.** Every case lands in one tenant.
  The columns and the query paths exist; what is missing is resolving a tenant
  from a request, which is the next thing auth should grow.
- **The event stream is a delivery accelerator, not a source of truth.** Every
  event carries state re-derivable from the checkpointer, so a client that
  misses one and refetches the case loses nothing. `GET /cases/{id}` is always
  authoritative.
- **Rate limiting is per process.** With N workers the effective limit is N times
  what is configured. It is there to stop runaway loops and casual abuse, not to
  meter a paying customer.
- **Migrations run on start.** `create_app` brings the schema to head via
  Alembic, so there is nothing to remember to do. A database created before
  migrations existed is adopted without data loss, because revision 0001 is
  idempotent. Every migration after it is a real `ALTER` -- see
  `src/voxgate/migrations/README.md`.

## Secrets

`.env` is gitignored and must stay that way. For GitHub Actions, put keys in
repository secrets and inject them as environment variables — the CI workflow
runs the offline suite and needs no secrets at all.

Never commit a key, and never paste one into a doc. If one is exposed, rotate it
at the provider; deleting the commit does not un-publish it.
