# VoxGate web (`apps/web`)

The VoxGate frontend: a Next.js 16 / React 19 app. It is deployed as its own
Vercel project, separate from the FastAPI backend at the repo root. The browser
talks same-origin and `next.config.ts` rewrites `/api/*` to the backend, so
CORS never comes into play — see `next.config.ts` for why.

```
browser ──▶ Next.js (apps/web) ──/api/*──▶ FastAPI (repo root) ──▶ Postgres
```

## Local development

```bash
cd apps/web
npm ci
npm run dev          # http://localhost:3000
```

Start the backend first (see the repo-root README; `uv run uvicorn
voxgate.service.app:app --port 8000`). dev defaults `API_ORIGIN` to
`http://127.0.0.1:8000`.

## Deploying to Vercel

The backend and this web app are two separate Vercel projects in the same
repository:

1. **Backend** — root directory is the repo root (Python/FastAPI). Already
   deployed; its URL is `API_ORIGIN` for this project.
2. **Web app** — a Vercel project whose **Root Directory** is set to `apps/web`.
   Vercel detects Next.js from `package.json` at that root automatically.

Environment variables:

| Variable | Where | Purpose |
|---|---|---|
| `API_ORIGIN` | server-side env, read at start | Backend origin that `/api/*` rewrites to. Changing it is a restart, not a rebuild. |
| `NEXT_PUBLIC_SITE_URL` | build-time | Canonical URL for sitemap/robots/OG metadata. Defaults to `https://voxgate.app`. Override with your real frontend URL. |

Do not set `NEXT_PUBLIC_API_URL` unless the frontend is served by something
that cannot rewrite `/api/*`; doing so reintroduces cross-origin calls and
requires `VOXGATE_CORS_ORIGINS` on the backend. See `env.example`.

## Notes

- `npm run lint` and `npm run build` run in CI (`.github/workflows/ci.yml`).
- `.env.local` is gitignored; `env.example` documents the variables.