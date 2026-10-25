# BluFire Platform: Setup Guide

This repo is the BluFire control plane. It registers, deploys, watches, backs up and secures every BluFire client
web app on Azure. You operate it through an admin web app and through Claude (MCP). Everything that runs, watches or
alerts is in Azure. GitHub holds the code, and an M2 Mac Mini at home is the one off-cloud check.

There are two audiences:

- **Gus:** read [Quick Setup](#quick-setup). It is the checklist to stand up Azure and migrate the apps.
- **Agents (Claude Code or any coding agent):** read everything from [1. Architecture](#1-architecture) on. It
  explains how the pieces fit, which files own what, and the rules you must follow.

---

## Quick Setup

Do the steps in order. Each step lists what it needs and how you know it worked. Run every command from the root of
this repo on your MacBook, connected to the UniFi network (the static IP). Away from home, connect to the UniFi VPN
first.

**Time:** about one day for steps A to E, then about half a day per app migration.

### A. Prepare (no Azure changes yet)

1. **Install tools on the MacBook:**
   `brew install azure-cli jq yq gh postgresql@17 python@3.12`, then `pip3 install pyyaml jsonschema`,
   `az bicep install` and `gh auth login` (bootstrap sets repo variables with `gh`).
2. **Confirm the static IP.** Check that your ISP gave the UniFi WAN a fixed address (`curl -s ifconfig.me`).
   Everything locks to it.
3. **Pick a domain for two host names,** for example `ops.blufireanalytics.com` (admin UI) and
   `mcp.blufireanalytics.com` (Claude). In the Microsoft Entra admin center, go to Custom domain names, add the
   domain and verify it with the TXT record. Entra only accepts the MCP URL on a verified domain, and Claude needs
   that.
4. **Require MFA on every sign-in** in the BluFire tenant, through Security defaults or a Conditional Access policy.
   Approvals rely on a fresh sign-in implying MFA.
5. **Create a cloud-only admin account** (for example `admin@<tenant>.onmicrosoft.com`) with a phishing-resistant
   method (passkey). Use it for bootstrap only. Keep its recovery codes offline.
6. **Create three subscriptions** in the Azure portal: `sub-blufire-platform`, `sub-blufire-backup` and
   `sub-blufire-sandbox`. Don't create client subscriptions yet.
7. **Create an Entra group** `pg-admins` with yourself in it. Note its object ID.
8. **Set up GitHub:**
   - Create the private repo `blufire-platform` in your GitHub org and push this code to it.
   - Create a GitHub App named `blufire-platform` with these repository permissions: Contents (read and write),
     Pull requests (read and write), Actions (read and write), Dependabot alerts (read), Metadata (read).
   - Install the App on `blufire-platform` and on every client app repo. Note the App ID and the installation ID
     (the number in the installation's URL), and download a private key `.pem`.
   - Protect `main`: require pull requests and passing checks, and add the App to the bypass list. The admin UI
     commits low-risk changes through the App.
   - Add org secrets `PLATFORM_APP_ID` and `PLATFORM_APP_PRIVATE_KEY`, available to the platform repo and the app
     repos.
9. **Fill in `platform.yaml`:** every `REPLACE` value (tenant id, the three subscription ids, GitHub org, static IP,
   alert email and phone, digest time zone, `pg-admins` object id, both domains). Keep `region: eastus2` unless you
   chose otherwise.
10. **Replace the demo registry files.** `registry/clients/demo-*.yaml` and `registry/apps/demo-*/` are examples.
    Delete them and create one client file per real client (ids are 2 to 10 characters) and one app file per real
    app (ids are 2 to 20 characters, unique across clients):
    - Your live production app: `stage: graduated`. The client's `subscription_id` comes in step F1; leave the
      app file out until then.
    - The three apps in refinement: `stage: incubating`, `client_data: false`, no images yet.
    Run `python3 tools/render_params.py --out build/params`. It must finish with no errors (warnings about unset
    domains or settings are expected until bootstrap fills them).
11. Commit and push. CI (`ci.yml`) runs tests and builds on every PR from now on.

**Done when:** `bootstrap/00-prereqs-check.sh` passes.

### B. Bootstrap Azure

Sign in as the cloud-only admin: `az login --tenant <tenant-id>`.

| # | Run | What happens | Check |
| --- | --- | --- | --- |
| B1 | `bootstrap/00-prereqs-check.sh` | Checks tools, sign-in and `platform.yaml`. Changes nothing | All green |
| B2 | `bootstrap/10-management-group-and-subscriptions.sh` | Creates `mg-blufire`, moves the three subscriptions under it, registers providers | Portal: Management groups shows `mg-blufire` with 3 subscriptions |
| B3 | `bootstrap/20-policy-and-defender.sh` | Policy baseline (region, tags, Postgres public access off), CI what-if role, Defender free tier check | Policy > Compliance lists the BluFire assignments |
| B4 | `bootstrap/30-entra-app-registrations.sh` | App registrations for platform-api (Admin and Agent roles), admin UI and MCP. **Prints the MCP client secret once: save it in your password manager** | `infra/platform-settings.json` has the ids |
| B5 | `bootstrap/40-github-oidc.sh` | Lets GitHub Actions sign in to Azure without secrets, and sets repo variables | Repo Settings > Variables shows `AZURE_*` |
| B6 | `bootstrap/50-deploy-backup.sh` | Immutable backup storage in `sub-blufire-backup` | Storage account `stblufirebkp...` exists |
| B7 | `bootstrap/60-deploy-platform.sh --github-app-key ~/Downloads/<app>.pem` | Control plane in passes: core resources, secrets, image builds in ACR, apps and worker jobs. It prints DNS records for your two host names | Script ends without errors |
| B8 | Create the DNS records it printed, then `bootstrap/60-deploy-platform.sh --github-app-key <pem> --domains-only` | Binds the custom domains with managed certificates | `https://ops.<domain>` loads the sign-in page |
| B9 | `bootstrap/70-deploy-sandbox.sh` | Shared sandbox: one Container Apps environment and one Postgres (B2s) | Portal: `rg-sandbox-shared` |
| B10 | `bootstrap/40-github-oidc.sh` (again) | Gives CI write access to the scan and mirror containers that B6 created | No errors |
| B11 | `bootstrap/50-deploy-backup.sh mac-mini` | Creates the Mac Mini's read-only identity and prints the certificate path | Save the `.pem` for step D |
| B12 | `git add infra/platform-settings.json infra/platform-images.json && git commit -m "bootstrap settings" && git push` | Records the ids and image digests the scripts wrote | `apply.yml` runs green on main |

**Done when:** you can sign in at `https://ops.<domain>` and the Fleet screen loads. Then confirm these:
- Azure Monitor > Alerts > Action groups > `ag-platform-p1`: send a test notification. It must reach your phone as
  push and SMS.
- Admin UI > More > Digest > Build digest now. The email arrives within a few minutes.
- Sentinel > Data connectors shows Azure Activity connected.

### C. Connect Claude

- **Claude (web, Desktop, mobile):** Settings > Connectors > Add custom connector. Use URL `https://mcp.<domain>/mcp`.
  Under Advanced settings, enter the MCP client ID (`mcpClientId` in `infra/platform-settings.json`) and the client
  secret from step B4. Sign in with your BluFire account when prompted.
- **Claude Code:**
  `claude mcp add --transport http --scope user --client-id <mcpClientId> --client-secret --callback-port 8765 blufire https://mcp.<domain>/mcp`,
  then run `/mcp` to sign in.
- Test by asking Claude "What's the fleet status?". To test approvals, ask it to propose a dev alert threshold
  change. The change must appear in the admin UI under Changes, waiting for your approval.

The MCP server only accepts traffic from your static IP and Anthropic's connector range (`160.79.104.0/21`), and
only your Entra account is assigned to it.

### D. Set up the Mac Mini

Follow `heartbeat/README.md`: copy the certificate from B11, store the heartbeat token, write
`~/.blufire/heartbeat.json`, and load the two launchd jobs.

**Done when:** `python3 ~/blufire/heartbeat/heartbeat.py` prints all targets as `true`, and a deliberately wrong
target URL sends you an iMessage.

### E. Lock the backups (after one week of good backups)

`bootstrap/50-deploy-backup.sh lock` makes the retention periods permanent: 90 days for nightly dumps and repo
mirrors, 365 days for pre-promotion dumps. Nobody can delete those backups early after this, including you.

### F. Migrate the live production app (straight to graduated)

1. Create the client's subscription `sub-<client>` in the portal and set `subscription_id` in
   `registry/clients/<client>.yaml`.
2. Add the app file with `stage: graduated`, then run
   `bootstrap/30-entra-app-registrations.sh client-app <client> <app> <frontend-host>`. Put the printed
   `entra_app_id` in the app file. Send the printed consent link to the client's Microsoft 365 admin.
3. Commit through a PR and approve it in the admin UI. Then run `bootstrap/80-onboard-client.sh <client>`
   (client network, Postgres servers, Key Vaults, db-ops jobs) and `bootstrap/90-graduate-app.sh <client> <app>`
   (secrets, app environments, database roles).
4. Update the app's code to the template pattern (see `templates/app/README.md`): Entra sign-in, managed identity
   Postgres, health endpoints, audit log, and the reusable build workflow. Push it. CI builds the images and
   deploys dev automatically.
5. Move the data: follow `docs/sop/migrate-from-supabase.md` (export, restore, verify, seed identity links).
6. Promote dev to cert, then cert to prod, from the app's screen in the admin UI (Promote button, then approve the
   change). Prod promotions take a pre-promotion dump first, and roll back automatically if the new revision is
   unhealthy.
7. Smoke test with the client, cut over, and keep Supabase paused for 30 days.

### G. Move the three apps in refinement to the sandbox

For each app:
1. Run `bootstrap/30-entra-app-registrations.sh client-app <client> <app> <frontend-host>` and put the id in the
   app file, then run `bootstrap/85-incubate-app.sh <client> <app>`.
2. Update the code to the template pattern and push. Dev deploys into the sandbox.
3. If the app needs its current Supabase data, use the migration SOP with the sandbox as the target. The sandbox
   server is shared across clients, so set `client_data: true` if real data lands there. The UI flags that.

### H. Graduate an app (when you decide)

Admin UI > the app > Graduate. Enter the client's subscription id and approve the change. Then run
`bootstrap/80-onboard-client.sh <client>` (first app for that client only) and
`bootstrap/90-graduate-app.sh <client> <app>`. The script removes the app's sandbox databases unless you pass
`--keep-sandbox`. Migrate the data from Supabase directly into the graduated databases (step F5), not from the
sandbox.

---

## 1. Architecture

```
 Gus (static IP) ──> admin UI (Next.js) ─┐
 Claude ───────────> MCP server ─────────┼──> platform-api (FastAPI) ──> GitHub: registry YAML (commits / PRs)
                                          │          │                         │
                                          │          └── state DB (Postgres)   └── apply.yml ──> Azure (Bicep)
 worker jobs (Container Apps Jobs) ───────┘
   pull from Azure Monitor, Sentinel, Defender, Dependabot, Trivy results, backup results
   start db-ops jobs (inside each private Postgres network) for dumps, restore tests, grants, cleanup
 Client staff (their own Entra ID) ──> client app frontend ──> backend (internal) ──> private Postgres
 Mac Mini (off-cloud) ──> checks prod health and the worker heartbeat; copies backups to a local drive nightly
```

**Two kinds of state:**
- **Desired state** lives in git: `platform.yaml`, `registry/clients/*.yaml`, `registry/apps/<client>/<app>.yaml`,
  `policies/approvals.yaml` and `alerts/defaults.yaml`. Images are pinned per environment by digest in the app
  file, so a promotion is a registry change.
- **Observed state** lives in the state DB: deployments, backups, restore tests, findings, incidents, drift, secret
  metadata, costs and the audit log. Only the worker and platform-api write it.

**One API, two front doors.** The admin UI and the MCP server are thin clients. Every permission check is in
platform-api, so neither front door can do more than the other's role allows.

**Alerting does not depend on the control plane.** Azure Monitor alert rules and Sentinel page Gus directly through
the action group. The worker's sync feeds the UI, the digest and Claude. The Mac Mini watches that the worker keeps
running.

### Environments and where apps run

| Stage | Subscription | Postgres | Backups |
| --- | --- | --- | --- |
| Incubating | `sub-blufire-sandbox`, shared by all incubating apps | One shared B2s server, one database per app per env | Point-in-time restore for 7 days only |
| Graduated | `sub-<client>`, one per client | Dedicated prod server (B2s) plus a shared dev and cert server (B1ms) per client | All four layers |

Every Postgres server is private: inside its VNet, Entra authentication only, no passwords.

## 2. Repository map

| Path | What it is | Owned by |
| --- | --- | --- |
| `platform.yaml` | Global settings: tenant, subscriptions, static IP, domains, alert contacts | Gus (approval required) |
| `registry/schema/*.json` | JSON Schemas for client and app files. CI and platform-api validate against them | Agents, through PR |
| `registry/clients/`, `registry/apps/` | Desired state per client and app | Admin UI, Claude (PR), CI dev bumps |
| `policies/approvals.yaml` | Which changes need approval | Gus (approval required) |
| `alerts/defaults.yaml` | Default thresholds, remediation SLAs, digest settings | Admin UI (low risk) |
| `infra/modules/`, `infra/stacks/` | Bicep: `platform`, `backup`, `sandbox`, `client`, `app` stacks | Agents, through PR |
| `infra/platform-settings.json` | Ids written by bootstrap (app registrations, principals, GitHub App). No secrets | Bootstrap scripts |
| `infra/platform-images.json` | Pinned digests of the three control plane images | `control-plane-images.yml` |
| `infra/scripts/deploy.py` | Deploys rendered parameters in order. Handles pre-promotion dumps, health checks and rollback | Agents |
| `tools/render_params.py` | Registry to Bicep parameter files, with validation and Azure name-length checks. `--names` prints platform names | Agents |
| `tools/migrate/` | Supabase export and Azure restore scripts | Agents |
| `bootstrap/` | One-time and per-client setup scripts (see `bootstrap/README.md`) | Agents |
| `control-plane/src/blufire_cp/` | platform-api (`api/`), worker (`worker/`), MCP server (`mcp_server.py`), shared modules | Agents |
| `control-plane/dbops/` | `blufire-dbops`: dump, restore test, grant, migrate, verify, drop (sandbox only) | Agents |
| `control-plane/ui/` | Admin UI (Next.js, Material 3). `UI_MOCK=1` runs it without an API | Agents |
| `heartbeat/` | Mac Mini heartbeat and off-cloud backup | Agents |
| `templates/app/` | Starting point for client app repos | Agents |
| `docs/api-contract.md` | platform-api endpoints and shapes | Keep in sync with `api/main.py` |
| `docs/runtime-config.md` | Every env var per image, the naming table, telemetry names | Keep in sync with Bicep |
| `docs/sop/` | Runbooks: Supabase migration, incident, restore | Agents |
| `.github/workflows/` | `ci`, `apply`, `control-plane-images`, `nightly-image-scan`, `nightly-repo-mirror`, `reusable-app-build` | Agents |

## 3. How changes flow

### A configuration change

1. Someone edits a setting in the admin UI, Claude calls `propose_registry_change`, or a PR edits YAML.
2. platform-api applies the JSON merge patch to the YAML (comments survive). It then validates the result against
   the schema and the cross-file rules: the client exists, a graduated app needs a client subscription, origin
   restriction can't be on with no networks, and min is at most max.
3. It classifies the change with `policies/approvals.yaml`.
   - **Low risk:** commits straight to `main` through the GitHub App. Examples: dev and cert scaling, alert
     thresholds, backup schedule.
   - **Approval needed:** opens a PR. This covers prod, origins, auth, secrets, cert images, stage,
     `client_data`, client files, policy files, creating or deleting files, and anything proposed by Claude.
4. Gus approves in the UI. That needs step-up: a fresh MFA sign-in, with an ID token no older than 10 minutes. The
   API then merges the PR.
5. A merge to `main` triggers `apply.yml`. It renders parameters, deploys only what changed (in dependency order)
   and writes a summary to the run.

### A release

1. Merging to an app repo's `main` runs `reusable-app-build.yml`: lint, tests, image build, Trivy gate, push to
   ACR. It then commits the new dev digests into the app file as a low-risk bot commit. `apply.yml` deploys dev.
2. **Promote dev to cert** (UI button or Claude's `request_promotion`): a change that copies the digests. It needs
   approval.
3. **Promote cert to prod:** same, with approval. `deploy.py` takes a pre-promotion dump through the db-ops job.
   It deploys the new revision, waits for it to be healthy and tags the release. If the revision is unhealthy, it
   redeploys the previous parameters.

### Drift

Every hour the worker compares each Container App with git: scale, images, non-secret env vars and origin rules.
Differences show on the Drift screen, and prod drift also alerts.
- **Adopt** opens a change that writes the live value into git.
- **Revert** re-runs `apply.yml` for that app and environment.

Never fix drift by clicking in the portal.

## 4. Contracts you must keep in sync

| Contract | Source of truth | Mirrors |
| --- | --- | --- |
| Resource names | `docs/runtime-config.md` Naming table | `control-plane/src/blufire_cp/naming.py`, `tools/render_params.py` (a test compares them) |
| Env vars per image | `docs/runtime-config.md` | `infra/modules/platform-core.bicep`, `infra/stacks/app.bicep`, `control-plane/src/blufire_cp/config.py`, `templates/app` |
| API endpoints and shapes | `docs/api-contract.md` | `control-plane/src/blufire_cp/api/main.py`, `control-plane/ui/lib/api.ts`, `mcp_server.py` tools |
| Registry shape | `registry/schema/*.json` | UI editors, `render_params.py` |
| Approval rules | `policies/approvals.yaml` | `policy.py` (logic only) |
| Alert trace names | `worker_heartbeat`, `backup_failed`, `restore_test_failed`, `drift_detected_prod` | `telemetry.py` emitters, `platform-core.bicep` alert rules |

## 5. Identities and permissions

| Identity | Used by | Can |
| --- | --- | --- |
| Gus (daily account) | Admin UI | `Admin` app role on platform-api: everything, approvals need step-up |
| Gus (cloud-only admin) | Bootstrap only | Owner on `mg-blufire`, Application Administrator |
| `id-platform-prod` | platform-api, MCP server, worker jobs | Reader on `mg-blufire`, Log Analytics Reader, start db-ops jobs, restart app revisions, Key Vault secrets (rotation), read backup results, the `Agent` role on platform-api (MCP), send email |
| `id-platform-dbops`, `id-<c>-dbops`, `id-sandbox-dbops` | db-ops jobs | Entra admin on their own Postgres servers, write dumps and results to backup storage |
| `id-<c>-<a>-<e>` | One app in one environment | Pull its images, read its own Key Vault secrets, connect to its own database |
| `gh-blufire-deploy` | `apply.yml` and image builds on platform `main` | Contributor and RBAC Administrator on `mg-blufire` |
| `gh-blufire-whatif` | PR checks | Custom what-if role plus Reader |
| `gh-blufire-builds` | App repo `main` builds | AcrPush on the platform registry only |
| `blufire-mac-mini` | Mac Mini | Read dumps and mirrors, write `dbops-results` receipts |
| GitHub App `blufire-platform` | platform-api, worker, CI | Commit, open and merge PRs, dispatch workflows, read Dependabot alerts |

Secrets live only in Key Vault. The UI and MCP show secret names, dates and a Rotate action, never values. Logs and
audit events identify people by Entra object id only.

## 6. Network rules

| Surface | Reachable from |
| --- | --- |
| Admin UI | Static IP only, and Entra sign-in |
| MCP server | Static IP plus `160.79.104.0/21` (Anthropic connectors), Entra OAuth, only Gus assigned |
| platform-api | Internal only (UI and MCP call it inside the environment). The Mac Mini reaches the heartbeat through the UI at `/api/heartbeat` |
| Client app frontends | Anyone by default. Optional origin restriction per app per environment: client CIDRs, the static IP and the availability test ranges in `infra/platform-settings.json` |
| Client app backends | Internal only |
| Postgres | Its own VNet only |
| Backup storage | Static IP, CI runner during one step, db-ops subnets, Mac Mini identity |

## 7. Local development

```bash
# Control plane API in dev mode: in-memory registry from this checkout, SQLite, no Azure, fake GitHub.
pip install -e "control-plane[dev]"
BLUFIRE_DEV_MODE=1 blufire-api            # http://localhost:8000/docs; add header X-Dev-Role: agent to act as Claude
BLUFIRE_DEV_MODE=1 blufire-mcp            # http://localhost:8080/mcp, no auth in dev mode
BLUFIRE_DEV_MODE=1 blufire-worker sync    # runs one job against the dev context

# Admin UI with fixture data (no API, fake Gus session)
cd control-plane/ui && npm ci && UI_MOCK=1 npm run dev
```

## 8. Verification (run before every push)

```bash
pytest -q control-plane/tests tools/tests
ruff check control-plane/src control-plane/tests control-plane/dbops tools heartbeat templates/app/backend
python3 tools/render_params.py --out build/params
for f in infra/modules/*.bicep infra/stacks/*.bicep; do bicep build "$f" --stdout >/dev/null || echo "FAIL $f"; done
for f in bootstrap/*.sh tools/migrate/*.sh heartbeat/*.sh; do bash -n "$f"; done
(cd control-plane/ui && npm run lint && npm run build)
(cd templates/app/backend && pytest -q)
```

The db-ops and identity-link tests also run against a real Postgres when you set `DBOPS_TEST_PGHOST` (and
`DBOPS_TEST_PGPORT`). CI does the same with a Postgres service container.

## 9. What is built and what is not

**Built and tested locally:**
- platform-api: all endpoints in the contract, roles, step-up, audit middleware and change classification.
- Worker jobs, the MCP server (tools, Entra token checks, protected resource metadata) and db-ops (dump and restore
  test exercised against Postgres 16).
- The admin UI (all screens, mock mode), the app template, the Supabase export (dry-run against a local database),
  Bicep (compiles cleanly) and the parameter renderer.

**Not yet run against real Azure or GitHub.** Expect small fixes on the first bootstrap run: API versions, role
names, ordering. That is normal for infrastructure that has only been compiled.

**Known gaps and open items:**
- App Key Vaults use RBAC without a firewall, because Container Apps reads secrets over the public endpoint.
  Private endpoints are a roadmap item.
- Availability tests fail on apps with origin restriction on, unless Azure's availability test ranges are added to
  `availabilityTestCidrs` in `infra/platform-settings.json`.
- Supabase Storage files are not migrated by the scripts; see the SOP.
- The Posture tab has no Defender Secure Score yet. It shows Defender recommendations as findings instead.
- Digest recipients and timing are edited in `alerts/defaults.yaml` and `platform.yaml`, not in the UI.
- Secret rotation generates a new random value. Use it only for secrets BluFire owns, not third-party API keys.

**Decisions made during the build that refine the blueprint:**
- Promotions are registry changes, so every environment's images are visible and versioned in git.
- Restore tests restore into a temporary database on the same server, then drop it. No throwaway servers.
- Changes proposed by Claude always open a PR, even when they are low risk.
- Container App names are `ca-<app>-fe|be-<env>`, because Azure caps them at 32 characters. Client ids are capped
  at 10 characters and app ids at 20.
- Postgres and Key Vault names carry a short hash, because those names are global across Azure.
