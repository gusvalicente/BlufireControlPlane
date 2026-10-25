# blufire-platform

BluFire's control plane for client web apps on Azure: one registry in git, one API, an admin UI, an MCP server for
Claude, scheduled worker jobs, db-ops jobs inside each private database network, and an off-cloud heartbeat.

Start with [SETUP.md](SETUP.md). The **Quick Setup** section there is the step-by-step checklist. The rest explains
the architecture for anyone (or any agent) changing this repo.

| Directory | Purpose |
| --- | --- |
| `registry/`, `platform.yaml`, `policies/`, `alerts/` | Desired state (edited through the admin UI, Claude or PRs) |
| `infra/` | Bicep stacks and the deploy script |
| `bootstrap/` | One-time and per-client setup scripts |
| `control-plane/` | platform-api, worker, MCP server, db-ops, admin UI |
| `templates/app/` | Starting point for client app repos |
| `tools/` | Parameter renderer, Supabase migration scripts |
| `heartbeat/` | Mac Mini heartbeat and off-cloud backup copy |
| `docs/` | API contract, runtime config and naming, runbooks |
