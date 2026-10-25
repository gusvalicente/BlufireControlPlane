// Types from docs/api-contract.md (platform-api v1). Keep in sync with the contract.

export type Env = "dev" | "cert" | "prod";
export const ENVS: Env[] = ["dev", "cert", "prod"];
export type Health = "healthy" | "degraded" | "down" | "scaled_to_zero" | "not_deployed" | "unknown";
export type Severity = "critical" | "high" | "medium" | "low";
export type Risk = "low" | "approval";

export interface EnvStatus {
  env: Env;
  health: Health;
  summary: string;
  release: string | null;
  p95_ms: number | null;
  error_rate_pct: number | null;
  replicas: { current: number; max: number } | null;
}

export type BadgeKind = "critical_finding" | "approval" | "drift" | "client_data_in_sandbox";

export interface AppSummary {
  id: string;
  client: string;
  client_name: string;
  name: string;
  stage: "incubating" | "graduated";
  client_data: boolean;
  envs: EnvStatus[];
  badges: { kind: BadgeKind; count: number }[];
}

export interface Me {
  oid: string;
  name: string;
  roles: string[];
  mfa_fresh: boolean;
}

export interface Fleet {
  headline: string;
  detail: string;
  prod_up: number;
  prod_total: number;
  open_p1: number;
  pending_approvals: number;
  critical_findings: number;
  drift_open: number;
  cost_mtd_usd: number;
  apps: AppSummary[];
}

export interface Contact {
  name: string;
  role: string;
  email?: string;
}

export interface Client {
  id: string;
  name: string;
  tenant_id: string;
  subscription_id: string | null;
  contacts?: Contact[];
  postgres?: { prod_sku?: string; nonprod_sku?: string; prod_high_availability?: boolean };
  notes?: string;
  apps: string[];
}

export interface OriginCidr {
  cidr: string;
  label: string;
}

export interface RegistryEnvironment {
  images?: { frontend?: string | null; backend?: string | null };
  release?: string | null;
  scale: { min: number; max: number };
  origins: { enabled: boolean; cidrs: OriginCidr[] };
  env_vars?: Record<string, string>;
  secrets?: string[];
}

export interface RegistryApp {
  id: string;
  client: string;
  name: string;
  repo: string;
  stage: "incubating" | "graduated";
  client_data: boolean;
  stack?: { frontend?: string; backend?: string; runtime_eol?: Record<string, string> };
  auth: { entra_app_id?: string | null; allowed_tenants: string[]; consent_granted?: boolean };
  environments: Record<Env, RegistryEnvironment>;
  alerts?: { latency_p95_ms?: number; error_rate_pct?: number };
  backup?: { nightly_utc?: string; pitr_retention_days?: number };
}

export interface AppDetail {
  registry: RegistryApp;
  path: string;
  summary: AppSummary;
  approval_fields: string[];
  admin_static_ip: string;
}

export interface SecretMeta {
  id: string;
  vault: string;
  name: string;
  app: string;
  env: Env;
  last_rotated: string | null;
  expires: string | null;
}

export interface Runtime {
  release: string | null;
  images: { frontend?: string | null; backend?: string | null };
  bicep_params: Record<string, unknown>;
  env_vars: Record<string, string>;
  secrets: Pick<SecretMeta, "name" | "last_rotated" | "expires">[];
}

export interface ChangeRequestIn {
  title: string;
  reason?: string;
  file: string;
  patch: object;
  create?: boolean;
  delete?: boolean;
}

export interface Change {
  id: string;
  title: string;
  reason: string | null;
  file: string;
  actor: { kind: "admin" | "agent" | "ci"; oid: string; name: string };
  risk: Risk;
  matched_rules: string[];
  status: "applied" | "pending" | "rejected" | "failed";
  diff: string;
  commit_sha: string | null;
  pr_number: number | null;
  pr_url: string | null;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
}

export interface Deployment {
  id: string;
  app: string;
  env: Env;
  release: string | null;
  image_digest: string;
  git_sha: string;
  approver: string | null;
  started_at: string;
  finished_at: string | null;
  result: "running" | "succeeded" | "failed" | "rolled_back";
}

export type BackupLayer = "pitr" | "pre_promotion" | "nightly" | "manual" | "off_cloud";

export interface Backup {
  id: string;
  app: string;
  env: Env;
  layer: BackupLayer;
  location: string;
  size_bytes: number | null;
  checksum: string | null;
  created_at: string;
  result: "ok" | "failed";
}

export interface RestoreTest {
  id: string;
  app: string;
  backup_id: string;
  started_at: string;
  duration_s: number | null;
  checks: string[];
  result: "passed" | "failed" | "running";
}

export interface Finding {
  id: string;
  source: "dependabot" | "trivy" | "defender" | "runtime_eol";
  app: string | null;
  env: Env | null;
  title: string;
  package: string | null;
  cve: string | null;
  severity: Severity;
  status: "open" | "acknowledged" | "resolved";
  first_seen: string;
  due_at: string | null;
  link: string | null;
  note: string | null;
}

export interface Incident {
  id: string;
  source: "sentinel" | "app_insights" | "heartbeat";
  severity: "p1" | "p2" | "p3";
  title: string;
  status: "open" | "closed";
  opened_at: string;
  closed_at: string | null;
  note: string | null;
  link: string | null;
}

export interface Drift {
  id: string;
  app: string;
  env: Env;
  resource: string;
  property: string;
  desired: string;
  live: string;
  changed_by: string | null;
  detected_at: string;
  status: "open" | "adopted" | "reverted";
}

export interface Costs {
  month: string;
  total_usd: number;
  by_client: { client: string; usd: number }[];
}

export interface AuditEvent {
  id: string;
  at: string;
  actor_kind: "admin" | "agent" | "ci" | "worker";
  actor: string;
  action: string;
  target: string;
  source_ip: string | null;
  result: "ok" | "denied" | "error";
}

// Contract v1 leaves `Item` undefined (reported as a gap). Assumed shape:
export interface DigestItem {
  title: string;
  detail?: string;
  app?: string;
  link?: string;
}

export interface Digest {
  generated_at: string;
  p1: DigestItem[];
  p2: DigestItem[];
  p3: DigestItem[];
  text: string;
}

export type OpAction = "backup" | "restore_test" | "scan" | "drift_check" | "digest";

export interface OperationQueued {
  operation_id: string;
  status: "queued";
}
