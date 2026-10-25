# Runtime configuration contract

Container images and the environment variables each one reads. Bicep (infra/) must set exactly these.
Secrets are Key Vault references on the Container App, never literal values.

## Images (all in the platform Azure Container Registry)

| Image | Built from | Runs as |
| --- | --- | --- |
| `blufire-control-plane` | `control-plane/Dockerfile` | Container App `ca-platform-api-prod` (command `blufire-api`), Container App `ca-platform-mcp-prod` (command `blufire-mcp`), Container Apps Jobs `caj-platform-<job>-prod` (command `blufire-worker <job>`) |
| `blufire-ui` | `control-plane/ui/Dockerfile` | Container App `ca-platform-ui-prod` |
| `blufire-dbops` | `control-plane/dbops/Dockerfile` | Container Apps Jobs inside each Postgres's network: `caj-<client>-dbops-<env>` (graduated) and `caj-sandbox-dbops` (sandbox). Command `blufire-dbops <command>` |

Why db-ops jobs exist: every Postgres server is private (VNet only). GitHub runners and the platform worker cannot reach
them, so dumps, restores, migrations and role setup run as jobs inside the database's own network. The worker starts
these jobs through Azure Resource Manager and reads their result files from backup storage.

## blufire-control-plane (api, mcp, worker)

| Variable | Used by | Value |
| --- | --- | --- |
| `AZURE_CLIENT_ID` | all | api and worker: client ID of `id-platform-prod`. mcp: client ID of `id-platform-mcp`, which holds only the Agent app role on platform-api |
| `ENTRA_TENANT_ID` | all | BluFire tenant ID |
| `API_AUDIENCE` | api | Application ID URI of the platform-api app registration, e.g. `api://blufire-platform-api` |
| `UI_CLIENT_ID` | api | Client ID of the admin UI app registration (audience of the step-up ID token) |
| `STEP_UP_ACRS` | api | Optional Conditional Access authentication context id (e.g. `c1`); when set, an access token carrying it also counts as step-up. Needs Entra ID P1 |
| `STATE_DB_HOST` | api, worker | `psql-platform-prod.postgres.database.azure.com` |
| `STATE_DB_NAME` | api, worker | `blufire` |
| `STATE_DB_USER` | api, worker | Name of the managed identity as created in Postgres (`id-platform-prod`) |
| `GITHUB_OWNER`, `GITHUB_REPO` | api, worker | Platform repo |
| `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID` | api, worker | GitHub App used for commits, PRs and merges |
| `GITHUB_APP_PRIVATE_KEY` | api, worker | Key Vault secret `github-app-private-key` |
| `HEARTBEAT_TOKEN` | api | Key Vault secret `heartbeat-token` |
| `LOG_ANALYTICS_WORKSPACE_ID` | api, worker | Workspace customer ID (GUID) of `log-platform-prod` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | all | App Insights for the platform itself |
| `BACKUP_STORAGE_ACCOUNT` | worker | Name of the backup storage account |
| `PLATFORM_API_URL` | mcp | Internal URL of platform-api |
| `MCP_AUDIENCE` | mcp | Client ID of the MCP app registration (tokens may carry it or `MCP_RESOURCE_URL` as `aud`) |
| `MCP_RESOURCE_URL` | mcp | `https://<domains.mcp>/mcp`; also the MCP app's Application ID URI |
| `MCP_ALLOWED_OIDS` | mcp | Comma-separated Entra object IDs allowed to use MCP (Gus) |
| `API_SCOPE` | mcp | `<API_AUDIENCE>/.default` (MCP calls the API with its managed identity, Agent role) |
| `BLUFIRE_DEV_MODE` | all | `1` only on a laptop: in-memory registry, fake GitHub, no Azure calls, SQLite state DB |

## blufire-ui

| Variable | Value |
| --- | --- |
| `AUTH_SECRET` | Key Vault secret `ui-auth-secret` |
| `AUTH_MICROSOFT_ENTRA_ID_ID` | Client ID of the admin UI app registration |
| `AUTH_MICROSOFT_ENTRA_ID_SECRET` | Key Vault secret `ui-entra-client-secret` |
| `AUTH_MICROSOFT_ENTRA_ID_ISSUER` | `https://login.microsoftonline.com/<tenant>/v2.0` |
| `PLATFORM_API_URL` | Internal URL of platform-api |
| `PLATFORM_API_SCOPE` | `<API_AUDIENCE>/.default` delegated scope (`<API_AUDIENCE>/access_as_user`) |
| `UI_MOCK` | `1` to serve fixture data without an API (local preview) |

The UI runs as `id-platform-ui`: AcrPull plus read access to exactly `ui-auth-secret` and `ui-entra-client-secret`.

## blufire-dbops

| Variable | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | Client ID of the client's `id-<client>-dbops` identity (Entra admin on its Postgres servers) |
| `PGHOST` | Server FQDN |
| `BACKUP_STORAGE_ACCOUNT` | Backup storage account name |
| `BACKUP_CONTAINER` | `pg-dumps` |
| `RESULT_CONTAINER` | `dbops-results` |
| Per-run arguments | Passed as job command args: `dump --app <app> --env <env> --database <db> --layer nightly\|pre_promotion`, `restore --blob <path> --database <db>`, `verify --database <db> --expect <blob>`, `grant --database <db> --principal <identity-name>`, `migrate-from-blob --blob <path> --database <db>` |

## Naming (single source of truth; infra and control plane must both follow it)

`<c>` = client id (2 to 10 characters), `<a>` = app id (2 to 20 characters, unique across clients), `<e>` = dev |
cert | prod, `<h4>` / `<h6>` = first 4 / 6 hex characters of the SHA-256 of the subscription id (global names must be
unique across Azure). Database names use underscores. `tools/render_params.py` fails when a name exceeds Azure's limit.

| Thing | Graduated (sub-`<c>`) | Incubating (sub-blufire-sandbox) |
| --- | --- | --- |
| App resource group | `rg-<c>-<a>-<e>` | `rg-sandbox-<c>-<a>` (all three envs) |
| Shared resource group (VNet, Postgres, Key Vaults, CAEs, db-ops jobs) | `rg-<c>-shared` | `rg-sandbox-shared` |
| Container Apps environment | `cae-<c>-prod`, `cae-<c>-nonprod` | `cae-sandbox` |
| Frontend / backend Container App (max 32) | `ca-<a>-fe-<e>` / `ca-<a>-be-<e>` | same names |
| App managed identity | `id-<c>-<a>-<e>` | same |
| Postgres server (global) | `psql-<c>-prod-<h4>`, `psql-<c>-nonprod-<h4>` | `psql-sandbox-<h4>` |
| Database | `<a>_<e>` (hyphens to underscores) | `<c>_<a>_<e>` |
| db-ops job (max 32) | `caj-<c>-dbops-prod`, `caj-<c>-dbops-nonprod` | `caj-sandbox-dbops` |
| db-ops identity | `id-<c>-dbops` | `id-sandbox-dbops` |
| Key Vault (global, max 24) | `kv-<c>-p-<h4>`, `kv-<c>-n-<h4>` | `kv-sandbox-<h6>` |
| App Insights | `appi-<c>-<a>-<e>` | same |

Platform names (`rg-platform-prod`, `psql-platform-<h4>`, `kv-blufire-<h6>`, `acrblufire<h6>`, the backup storage
account `stblufirebkp<h6>`, ...) are printed by `python tools/render_params.py --names`. The platform db-ops job runs as
`id-platform-dbops`, so the platform identity stays read-only on backups.

Worker telemetry the alert rules read (App Insights `AppTraces`, field `Message`): `worker_heartbeat`,
`backup_failed`, `restore_test_failed`, `drift_detected_prod`. Each carries custom dimensions `app`, `env`, `detail`.

Digest email goes out through Azure Communication Services Email (Azure-managed sender domain), env vars
`ACS_ENDPOINT` and `DIGEST_SENDER` on the worker.

## Client app containers (set by infra/stacks/app.bicep, read by templates/app)

| Variable | Frontend | Backend | Value |
| --- | --- | --- | --- |
| `APP_ID`, `APP_ENV` | yes | yes | Registry app id and `dev` / `cert` / `prod` |
| `AZURE_CLIENT_ID` | yes | yes | Client ID of `id-<c>-<a>-<e>` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | yes | yes | `appi-<c>-<a>-<e>` |
| `ENTRA_CLIENT_ID` | yes | yes | The app's multi-tenant Entra app registration (`auth.entra_app_id`) |
| `ALLOWED_TENANTS` | yes | yes | Comma-separated `auth.allowed_tenants` |
| `BACKEND_URL` | yes | | Internal URL of the backend Container App (`http://ca-<c>-<a>-be-<e>`) |
| `AUTH_SECRET`, `ENTRA_CLIENT_SECRET` | yes | | Key Vault references `<app>-auth-secret`, `<app>-entra-client-secret` |
| `PGHOST`, `PGDATABASE`, `PGUSER` | | yes | Server FQDN, database name from the Naming table, `PGUSER` = `id-<c>-<a>-<e>` |
| `env_vars` from the registry | yes | yes | Non-secret values, both containers |
| `secrets` from the registry | yes | yes | Key Vault references, exposed with the secret name upper-cased and hyphens as underscores |

Each app identity gets Key Vault Secrets User on its own secrets only (one role assignment per secret: the
registry `secrets` list plus `<app>-auth-secret` and `<app>-entra-client-secret`). A secret listed in the registry
must already exist in the vault before the deployment, or the role assignment fails. Create it with
`az keyvault secret set` first, then add its name to the app file.
