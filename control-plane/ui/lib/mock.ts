import "server-only";
import type {
  AppDetail, AuditEvent, Backup, Change, ChangeRequestIn, Client, Costs, Deployment, Digest, Drift, Finding,
  Fleet, Incident, Me, RestoreTest, Runtime, SecretMeta,
} from "./types";
import { matchedRules, mergePatch, patchPaths } from "./approval";
import appsJson from "./fixtures/apps.json";
import auditJson from "./fixtures/audit.json";
import backupsJson from "./fixtures/backups.json";
import changesJson from "./fixtures/changes.json";
import clientsJson from "./fixtures/clients.json";
import costsJson from "./fixtures/costs.json";
import deploymentsJson from "./fixtures/deployments.json";
import digestJson from "./fixtures/digest.json";
import driftJson from "./fixtures/drift.json";
import findingsJson from "./fixtures/findings.json";
import incidentsJson from "./fixtures/incidents.json";
import meJson from "./fixtures/me.json";
import restoreJson from "./fixtures/restore-tests.json";
import runtimeJson from "./fixtures/runtime.json";
import secretsJson from "./fixtures/secrets.json";

// In-memory state for local previews. Mutations last until the server restarts.
const clone = <T>(v: unknown): T => structuredClone(v) as T;
const g = globalThis as unknown as { __blufireMock?: ReturnType<typeof seed> };

function seed() {
  return {
    apps: clone<AppDetail[]>(appsJson),
    clients: clone<Client[]>(clientsJson),
    runtime: clone<Record<string, Record<string, Runtime>>>(runtimeJson),
    changes: clone<Change[]>(changesJson),
    patches: {} as Record<string, object>,
    deployments: clone<Deployment[]>(deploymentsJson),
    backups: clone<Backup[]>(backupsJson),
    restore: clone<RestoreTest[]>(restoreJson),
    findings: clone<Finding[]>(findingsJson),
    incidents: clone<Incident[]>(incidentsJson),
    drift: clone<Drift[]>(driftJson),
    secrets: clone<SecretMeta[]>(secretsJson),
    costs: clone<Record<string, Costs>>(costsJson),
    audit: clone<AuditEvent[]>(auditJson),
    digest: clone<Digest>(digestJson),
    me: clone<Me>(meJson),
    seq: 100,
  };
}

function db() {
  if (!g.__blufireMock) g.__blufireMock = seed();
  return g.__blufireMock;
}

class MockError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

function nextId(prefix: string) {
  return `${prefix}_${++db().seq}`;
}

function audit(action: string, target: string) {
  db().audit.unshift({
    id: nextId("aud"), at: new Date().toISOString(), actor_kind: "admin", actor: "Gus",
    action, target, source_ip: "192.0.2.17", result: "ok",
  });
}

function fleet(): Fleet {
  const d = db();
  const apps = d.apps.map((a) => a.summary);
  const prod = apps.map((a) => a.envs.find((e) => e.env === "prod")!);
  const prodUp = prod.filter((e) => e.health === "healthy" || e.health === "degraded").length;
  const pending = d.changes.filter((c) => c.status === "pending").length;
  const critical = d.findings.filter((f) => f.status === "open" && f.severity === "critical").length;
  const driftOpen = d.drift.filter((x) => x.status === "open").length;
  const p1 = d.incidents.filter((i) => i.status === "open" && i.severity === "p1").length;
  const allUp = prodUp === apps.length;
  return {
    headline: allUp ? `All ${apps.length} prod apps are up` : `${apps.length - prodUp} prod app down`,
    detail: `${pending} change${pending === 1 ? "" : "s"} wait for your approval. ${critical} critical finding${critical === 1 ? " is" : "s are"} due soon.`,
    prod_up: prodUp, prod_total: apps.length, open_p1: p1, pending_approvals: pending,
    critical_findings: critical, drift_open: driftOpen,
    cost_mtd_usd: d.costs["2026-10"]?.total_usd ?? 0, apps,
  };
}

function findApp(id: string) {
  const app = db().apps.find((a) => a.registry.id === id);
  if (!app) throw new MockError(404, "not_found", `App ${id} not found`);
  return app;
}

function yamlish(value: unknown, indent = ""): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  return Object.entries(value as Record<string, unknown>)
    .map(([k, v]) =>
      v !== null && typeof v === "object" && !Array.isArray(v)
        ? `${indent}${k}:\n${yamlish(v, indent + "  ")}`
        : `${indent}${k}: ${JSON.stringify(v)}`,
    )
    .join("\n");
}

function createChange(body: ChangeRequestIn): Change {
  const d = db();
  const app = d.apps.find((a) => a.path === body.file);
  const paths = patchPaths(body.patch);
  const rules = app ? matchedRules(app.approval_fields, paths) : ["files"];
  const risk = rules.length ? "approval" : "low";
  const id = nextId("chg");
  const lines = yamlish(body.patch).split("\n");
  const change: Change = {
    id, title: body.title, reason: body.reason ?? null, file: body.file,
    actor: { kind: "admin", oid: d.me.oid, name: d.me.name }, risk, matched_rules: rules,
    status: risk === "low" ? "applied" : "pending",
    diff: `--- a/${body.file}\n+++ b/${body.file}\n@@ -1,${lines.length} +1,${lines.length} @@\n${lines.map((l) => "+" + l).join("\n")}\n`,
    commit_sha: risk === "low" ? Math.random().toString(16).slice(2, 9) : null,
    pr_number: risk === "low" ? null : d.seq, pr_url: risk === "low" ? null : `https://github.com/example/blufire-platform/pull/${d.seq}`,
    created_at: new Date().toISOString(), decided_at: risk === "low" ? new Date().toISOString() : null,
    decided_by: risk === "low" ? d.me.name : null,
  };
  d.changes.unshift(change);
  d.patches[id] = body.patch;
  if (risk === "low" && app) app.registry = mergePatch(app.registry, body.patch);
  audit("change.create", id);
  return change;
}

function decide(id: string, approve: boolean): Change {
  const d = db();
  const c = d.changes.find((x) => x.id === id);
  if (!c) throw new MockError(404, "not_found", "Change not found");
  if (c.status !== "pending") throw new MockError(409, "not_pending", "This change was already decided");
  c.status = approve ? "applied" : "rejected";
  c.decided_at = new Date().toISOString();
  c.decided_by = d.me.name;
  if (approve) {
    c.commit_sha = Math.random().toString(16).slice(2, 9);
    const app = d.apps.find((a) => a.path === c.file);
    const patch = d.patches[id];
    if (app && patch) app.registry = mergePatch(app.registry, patch);
  }
  audit(approve ? "change.approve" : "change.reject", id);
  return c;
}

export async function mockCall<T>(method: string, fullPath: string, body?: unknown): Promise<T> {
  const d = db();
  const url = new URL(fullPath, "http://mock");
  const q = url.searchParams;
  const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const route = `${method} /${parts.join("/")}`;
  const is = (re: RegExp) => re.test(route);
  const filterBy = <R extends { app?: string | null; env?: string | null }>(rows: R[]) =>
    rows.filter((r) => (!q.get("app") || r.app === q.get("app")) && (!q.get("env") || r.env === q.get("env")));

  let out: unknown;
  if (route === "GET /me") out = d.me;
  else if (route === "GET /fleet") out = fleet();
  else if (route === "GET /clients") out = d.clients;
  else if (route === "GET /apps") out = d.apps.map((a) => a.summary);
  else if (is(/^GET \/apps\/[^/]+$/)) out = findApp(parts[1]);
  else if (is(/^GET \/apps\/[^/]+\/environments\/(dev|cert|prod)\/runtime$/)) {
    findApp(parts[1]);
    out = d.runtime[parts[1]]?.[parts[3]];
  } else if (is(/^POST \/apps\/[^/]+\/graduate$/)) {
    const app = findApp(parts[1]);
    out = createChange({
      title: `Graduate ${app.registry.name}`, file: app.path,
      patch: { stage: "graduated" }, reason: `Target subscription ${(body as { subscription_id: string }).subscription_id}`,
    });
  } else if (route === "POST /changes") out = createChange(body as ChangeRequestIn);
  else if (route === "GET /changes") {
    const status = q.get("status") ?? "pending";
    out = d.changes.filter((c) => status === "all" || c.status === status);
  } else if (is(/^GET \/changes\/[^/]+$/)) {
    out = d.changes.find((c) => c.id === parts[1]);
    if (!out) throw new MockError(404, "not_found", "Change not found");
  } else if (is(/^POST \/changes\/[^/]+\/approve$/)) out = decide(parts[1], true);
  else if (is(/^POST \/changes\/[^/]+\/reject$/)) out = decide(parts[1], false);
  else if (route === "GET /deployments") out = filterBy(d.deployments);
  else if (route === "GET /backups") out = filterBy(d.backups);
  else if (route === "GET /restore-tests") out = filterBy(d.restore);
  else if (route === "GET /findings") {
    const status = q.get("status") ?? "open";
    const sev = q.get("severity");
    out = d.findings.filter(
      (f) => (status === "open" ? f.status !== "resolved" : f.status === "resolved") && (!sev || f.severity === sev),
    );
  } else if (is(/^POST \/findings\/[^/]+\/ack$/)) {
    const f = d.findings.find((x) => x.id === parts[1]);
    if (!f) throw new MockError(404, "not_found", "Finding not found");
    const b = body as { note: string; false_positive: boolean };
    f.status = b.false_positive ? "resolved" : "acknowledged";
    f.note = b.note;
    audit("finding.ack", f.id);
    out = f;
  } else if (route === "GET /incidents") out = d.incidents.filter((i) => !q.get("status") || i.status === q.get("status"));
  else if (route === "GET /drift") {
    const s = q.get("status");
    out = d.drift.filter((x) => !s || (s === "open" ? x.status === "open" : x.status !== "open"));
  } else if (is(/^POST \/drift\/[^/]+\/(adopt|revert)$/)) {
    const x = d.drift.find((r) => r.id === parts[1]);
    if (!x) throw new MockError(404, "not_found", "Drift item not found");
    if (parts[2] === "adopt") {
      const app = findApp(x.app);
      out = createChange({ title: `Adopt drift: ${x.property} = ${x.live}`, file: app.path, patch: { environments: { [x.env]: {} } } });
      x.status = "adopted";
    } else {
      x.status = "reverted";
      out = { operation_id: nextId("op") };
    }
    audit(`drift.${parts[2]}`, x.id);
  } else if (route === "GET /secrets") out = filterBy(d.secrets);
  else if (is(/^POST \/secrets\/[^/]+\/rotate$/)) {
    const s = d.secrets.find((x) => x.id === parts[1]);
    if (!s) throw new MockError(404, "not_found", "Secret not found");
    s.last_rotated = new Date().toISOString();
    audit("secret.rotate", s.id);
    out = { operation_id: nextId("op") };
  } else if (route === "GET /costs") {
    const month = q.get("month") ?? "2026-10";
    out = d.costs[month] ?? { month, total_usd: 0, by_client: [] };
  } else if (route === "GET /audit") {
    const limit = Number(q.get("limit") ?? 50);
    const before = q.get("before");
    const start = before ? d.audit.findIndex((a) => a.id === before) + 1 : 0;
    out = d.audit.slice(start, start + limit);
  } else if (route === "GET /digest/latest") out = d.digest;
  else if (is(/^POST \/ops\/(backup|restore_test|scan|drift_check|digest)$/)) {
    audit(`ops.${parts[1]}`, [(body as { app?: string })?.app, (body as { env?: string })?.env].filter(Boolean).join("/") || "all");
    out = { operation_id: nextId("op"), status: "queued" };
  } else throw new MockError(404, "not_found", `No mock for ${route}`);

  return clone<T>(out);
}

export { MockError };
