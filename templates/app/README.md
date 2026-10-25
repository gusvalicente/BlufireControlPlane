# BluFire client app template

Starting point for every client app: a Next.js frontend and a FastAPI backend in one repo. The admin UI's New app
wizard (or `bootstrap/85-incubate-app.sh`) copies this folder into a new private repo.

## What you get

| Piece | Where | Notes |
| --- | --- | --- |
| Sign-in with the client's Entra ID | `frontend/auth.ts`, `backend/app/auth.py` | Multi-tenant app restricted to `ALLOWED_TENANTS`; checked in both |
| Health probes | `backend /healthz`, `/readyz`; `frontend /api/health` | Container Apps probes and availability tests use these |
| Audit log | `backend/app/audit.py` | One event per request, Entra object id only, no personal data |
| Postgres with managed identity | `backend/app/db.py` | Entra token per connection, no stored password |
| Migrations | `backend/migrations/*.sql`, `python -m app.migrate` | Applied once each, in name order |
| Supabase user linking | `backend/app/identity.py`, `0001_identity_map.sql` | Links migrated users on first sign-in |
| Telemetry | Azure Monitor OpenTelemetry in both | Sends to the app's App Insights |
| CI | `.github/workflows/build.yml` | Calls the platform's reusable build: lint, test, Trivy, push, dev deploy |
| Dependency updates | `.github/dependabot.yml` | Weekly PRs for pip, npm, Docker base images, Actions |

The browser only talks to the frontend. The frontend calls the backend server-side at `BACKEND_URL` (internal to
Azure) with the user's access token. Environment variables are listed in the platform repo's
`docs/runtime-config.md` (Client app containers).

## Local development

```bash
cd backend && pip install -e ".[dev]" && pytest
cd frontend && npm install && npm run dev
```
Local Postgres: set `PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLMODE=disable`.
