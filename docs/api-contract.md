# platform-api contract (v1)

Base path: `/api/v1`. JSON only. All timestamps are ISO 8601 UTC strings. All ids are strings.
Every request needs `Authorization: Bearer <Entra access token>` for the platform-api app registration.

## Roles

| Role | Who | Can |
| --- | --- | --- |
| `Admin` | Gus, through the admin UI | Everything. Approve and secret rotation need step-up: header `X-Step-Up-Token` carrying the user's ID token (aud = UI client id, same `oid`, `auth_time` within 10 minutes, `amr` contains `mfa` when present; the tenant must require MFA on every sign-in), or an access token whose `acrs` claim holds `STEP_UP_ACRS`. |
| `Agent` | MCP server (Claude or any future model) | Read everything, run safe ops, propose changes. Never approve, merge, reject, delete, rotate secrets, or read secret values. |

Errors: `{"error": {"code": "string", "message": "string"}}` with HTTP 400/401/403/404/409/422.
`403 step_up_required` tells the UI to re-authenticate with MFA and retry.

## Shared shapes

```ts
type Env = "dev" | "cert" | "prod";
type Health = "healthy" | "degraded" | "down" | "scaled_to_zero" | "not_deployed" | "unknown";
type Severity = "critical" | "high" | "medium" | "low";
type Risk = "low" | "approval";

interface EnvStatus {
  env: Env;
  health: Health;
  summary: string;            // "Up 99.98%", "E2E pending", "Scaled to 0"
  release: string | null;
  p95_ms: number | null;
  error_rate_pct: number | null;
  replicas: { current: number; max: number } | null;
}

interface AppSummary {
  id: string; client: string; client_name: string; name: string;
  stage: "incubating" | "graduated"; client_data: boolean;
  envs: EnvStatus[];          // always dev, cert, prod in that order
  badges: { kind: "critical_finding" | "approval" | "drift" | "client_data_in_sandbox"; count: number }[];
}
```

## Endpoints

| Method | Path | Role | Body | Returns |
| --- | --- | --- | --- | --- |
| GET | `/me` | any | | `{oid, name, roles: string[], mfa_fresh: boolean}` |
| GET | `/fleet` | any | | `{headline: string, detail: string, prod_up: number, prod_total: number, open_p1: number, pending_approvals: number, critical_findings: number, drift_open: number, cost_mtd_usd: number, apps: AppSummary[]}` |
| GET | `/clients` | any | | `Client[]` (registry fields + `apps: string[]`) |
| GET | `/apps` | any | | `AppSummary[]` |
| GET | `/apps/{app_id}` | any | | `{registry: <app YAML as JSON>, path: string, summary: AppSummary, approval_fields: string[], admin_static_ip: string}` (`approval_fields` = dotted paths that need approval) |
| GET | `/apps/{app_id}/environments/{env}/runtime` | any | | `{release, images, bicep_params: object, env_vars: object, secrets: {name, last_rotated, expires}[]}` read only, secret values never included |
| POST | `/changes` | Admin, Agent | `ChangeRequestIn` | `Change` (201) |
| GET | `/changes?status=pending\|applied\|rejected\|all` | any | | `Change[]` |
| GET | `/changes/{id}` | any | | `Change` (includes `diff`) |
| POST | `/changes/{id}/approve` | Admin + step-up | | `Change` |
| POST | `/changes/{id}/reject` | Admin | `{reason: string}` | `Change` |
| GET | `/deployments?app=&env=` | any | | `Deployment[]` |
| GET | `/backups?app=&env=` | any | | `Backup[]` |
| GET | `/restore-tests?app=` | any | | `RestoreTest[]` |
| GET | `/findings?status=open\|resolved&severity=` | any | | `Finding[]` |
| POST | `/findings/{id}/ack` | Admin | `{note: string, false_positive: boolean}` | `Finding` |
| GET | `/incidents?status=open\|closed` | any | | `Incident[]` |
| GET | `/drift?status=open\|resolved` | any | | `Drift[]` |
| POST | `/drift/{id}/adopt` | Admin, Agent | | `Change` (a change request that writes the live value into git) |
| POST | `/drift/{id}/revert` | Admin, Agent | | `{operation_id}` (re-applies git; prod needs approval) |
| GET | `/secrets?app=&env=` | any | | `SecretMeta[]` |
| POST | `/secrets/{id}/rotate` | Admin + step-up | | `{operation_id}` |
| GET | `/costs?month=YYYY-MM` | any | | `{month, total_usd, by_client: {client, usd}[]}` |
| GET | `/audit?limit=&before=` | any | | `AuditEvent[]` |
| GET | `/digest/latest` | any | | `{generated_at, p1: Item[], p2: Item[], p3: Item[], text: string}` |
| POST | `/ops/{action}` | Admin, Agent | `{app?: string, env?: Env}` | `{operation_id, status: "queued"}`; actions: `backup`, `restore_test`, `scan`, `drift_check`, `digest` |
| POST | `/apps/{app_id}/graduate` | Admin | `{subscription_id: uuid}` | `Change` (opens the graduation PR) |
| POST | `/logs/query` | Admin, Agent | `{kql: string, timespan?: "P1D"}` | `{rows: object[]}`; must start with an allowlisted table, capped at 200 rows |
| GET | `/heartbeat` | heartbeat token | | `{worker_last_run: string \| null, jobs: {[job]: {ok, last_finished}}, ok: boolean}` |

Health probes outside `/api/v1`: `GET /healthz` (process up), `GET /readyz` (state DB reachable).

### Change requests

```ts
interface ChangeRequestIn {
  title: string;                       // "Enable origin restriction"
  reason?: string;
  file: string;                        // repo-relative, e.g. "registry/apps/demo-cpa/intake-portal.yaml"
  patch: object;                       // RFC 7386 JSON merge patch applied to the YAML document
  // create a file: patch is the whole document and create=true; delete: delete=true and patch={}
  create?: boolean; delete?: boolean;
}

interface Change {
  id: string; title: string; reason: string | null;
  file: string; actor: { kind: "admin" | "agent" | "ci"; oid: string; name: string };
  risk: Risk;                          // "low" commits directly; "approval" opens a PR
  matched_rules: string[];             // which approval rules matched
  status: "applied" | "pending" | "rejected" | "failed";
  diff: string;                        // unified diff of the YAML file
  commit_sha: string | null; pr_number: number | null; pr_url: string | null;
  created_at: string; decided_at: string | null; decided_by: string | null;
}
```

### Other records

```ts
interface Deployment { id; app; env: Env; release: string | null; image_digest: string; git_sha: string; approver: string | null; started_at; finished_at: string | null; result: "running" | "succeeded" | "failed" | "rolled_back" }
interface Backup { id; app; env: Env; layer: "pitr" | "pre_promotion" | "nightly" | "manual" | "off_cloud"; location: string; size_bytes: number | null; checksum: string | null; created_at; result: "ok" | "failed" }
interface RestoreTest { id; app; backup_id: string; started_at; duration_s: number | null; checks: string[]; result: "passed" | "failed" | "running" }
interface Finding { id; source: "dependabot" | "trivy" | "defender" | "runtime_eol"; app: string | null; env: Env | null; title: string; package: string | null; cve: string | null; severity: Severity; status: "open" | "acknowledged" | "resolved"; first_seen; due_at: string | null; link: string | null; note: string | null }
interface Incident { id; source: "sentinel" | "app_insights" | "heartbeat"; severity: "p1" | "p2" | "p3"; title; status: "open" | "closed"; opened_at; closed_at: string | null; note: string | null; link: string | null }
interface Drift { id; app; env: Env; resource: string; property: string; desired: string; live: string; changed_by: string | null; detected_at; status: "open" | "adopted" | "reverted" }
interface SecretMeta { id; vault: string; name: string; app: string; env: Env; last_rotated: string | null; expires: string | null }
interface AuditEvent { id; at; actor_kind: "admin" | "agent" | "ci" | "worker"; actor: string; action: string; target: string; source_ip: string | null; result: "ok" | "denied" | "error" }
```
