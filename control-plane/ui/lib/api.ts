import "server-only";
import type {
  AppDetail, AppSummary, AuditEvent, Backup, Change, ChangeRequestIn, Client, Costs, Deployment, Digest, Drift,
  Env, Finding, Fleet, Incident, Me, OperationQueued, OpAction, RestoreTest, Runtime, SecretMeta, Severity,
} from "./types";
import { isMock } from "./mode";
import { mockCall } from "./mock";
import { getAccessToken, getIdToken } from "./token";

export * from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

type Method = "GET" | "POST";

function qs(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (!entries.length) return "";
  return "?" + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString();
}

async function call<T>(method: Method, path: string, body?: unknown, opts: { stepUp?: boolean } = {}): Promise<T> {
  if (isMock()) return mockCall<T>(method, path, body);

  const token = await getAccessToken();
  if (!token) throw new ApiError(401, "not_signed_in", "Sign in again to continue.");
  const idToken = opts.stepUp ? await getIdToken() : null;

  const res = await fetch(`${process.env.PLATFORM_API_URL}/api/v1${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(idToken ? { "X-Step-Up-Token": idToken } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });

  if (!res.ok) {
    let code = "http_" + res.status;
    let message = res.statusText || "Request failed";
    try {
      const data = await res.json();
      if (data?.error) {
        code = data.error.code ?? code;
        message = data.error.message ?? message;
      }
    } catch {
      // Non-JSON error body: keep the HTTP status text.
    }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

export const api = {
  me: () => call<Me>("GET", "/me"),
  fleet: () => call<Fleet>("GET", "/fleet"),
  clients: () => call<Client[]>("GET", "/clients"),
  apps: () => call<AppSummary[]>("GET", "/apps"),
  app: (id: string) => call<AppDetail>("GET", `/apps/${encodeURIComponent(id)}`),
  runtime: (id: string, env: Env) =>
    call<Runtime>("GET", `/apps/${encodeURIComponent(id)}/environments/${env}/runtime`),
  graduate: (id: string, subscription_id: string) =>
    call<Change>("POST", `/apps/${encodeURIComponent(id)}/graduate`, { subscription_id }),

  createChange: (body: ChangeRequestIn) => call<Change>("POST", "/changes", body),
  changes: (status: "pending" | "applied" | "rejected" | "all" = "pending") =>
    call<Change[]>("GET", `/changes${qs({ status })}`),
  change: (id: string) => call<Change>("GET", `/changes/${encodeURIComponent(id)}`),
  approve: (id: string) => call<Change>("POST", `/changes/${encodeURIComponent(id)}/approve`, undefined, { stepUp: true }),
  reject: (id: string, reason: string) =>
    call<Change>("POST", `/changes/${encodeURIComponent(id)}/reject`, { reason }),

  deployments: (app?: string, env?: Env) => call<Deployment[]>("GET", `/deployments${qs({ app, env })}`),
  backups: (app?: string, env?: Env) => call<Backup[]>("GET", `/backups${qs({ app, env })}`),
  restoreTests: (app?: string) => call<RestoreTest[]>("GET", `/restore-tests${qs({ app })}`),

  findings: (status: "open" | "resolved" = "open", severity?: Severity) =>
    call<Finding[]>("GET", `/findings${qs({ status, severity })}`),
  ackFinding: (id: string, note: string, false_positive: boolean) =>
    call<Finding>("POST", `/findings/${encodeURIComponent(id)}/ack`, { note, false_positive }),
  incidents: (status?: "open" | "closed") => call<Incident[]>("GET", `/incidents${qs({ status })}`),

  drift: (status?: "open" | "resolved") => call<Drift[]>("GET", `/drift${qs({ status })}`),
  adoptDrift: (id: string) => call<Change>("POST", `/drift/${encodeURIComponent(id)}/adopt`),
  revertDrift: (id: string) => call<{ operation_id: string }>("POST", `/drift/${encodeURIComponent(id)}/revert`),

  secrets: (app?: string, env?: Env) => call<SecretMeta[]>("GET", `/secrets${qs({ app, env })}`),
  rotateSecret: (id: string) =>
    call<{ operation_id: string }>("POST", `/secrets/${encodeURIComponent(id)}/rotate`, undefined, { stepUp: true }),

  costs: (month?: string) => call<Costs>("GET", `/costs${qs({ month })}`),
  audit: (limit = 50, before?: string) => call<AuditEvent[]>("GET", `/audit${qs({ limit, before })}`),
  digest: () => call<Digest>("GET", "/digest/latest"),
  op: (action: OpAction, app?: string, env?: Env) => call<OperationQueued>("POST", `/ops/${action}`, { app, env }),
};
