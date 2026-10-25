"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { graduateApp, proposeChange, type ActionResult } from "@/app/actions";
import { Icon } from "@/components/Icon";
import { Sheet } from "@/components/Sheet";
import { Snackbar, type Snack } from "@/components/Snackbar";
import { needsApproval } from "@/lib/approval";
import { ENV_LABEL } from "@/lib/format";
import type { Env, OriginCidr, RegistryApp } from "@/lib/types";

type Editor = "origins" | "scale" | "alerts" | "backup" | "tenants" | "graduate" | null;

const CIDR_RE = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d|[12]\d|3[0-2])$/;
const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function validCidr(v: string): boolean {
  const m = v.trim().match(CIDR_RE);
  return !!m && m.slice(1, 5).every((o) => Number(o) <= 255);
}

function Lock({ show }: { show: boolean }) {
  if (!show) return null;
  return <span className="lock"><Icon n="lock" />Approval</span>;
}

interface Props {
  app: RegistryApp;
  path: string;
  env: Env;
  approvalFields: string[];
  lockedOrigins: OriginCidr[];
  isAdmin: boolean;
}

export function AppConfig({ app, path, env, approvalFields, lockedOrigins, isAdmin }: Props) {
  const router = useRouter();
  const [editor, setEditor] = useState<Editor>(null);
  const [snack, setSnack] = useState<Snack | null>(null);
  const [pending, start] = useTransition();
  const e = app.environments[env];
  const prodOrApproval = (field: string) => needsApproval(approvalFields, field);

  // Editor state, reset each time a sheet opens.
  const [originsOn, setOriginsOn] = useState(e.origins.enabled);
  const [cidrs, setCidrs] = useState<OriginCidr[]>(e.origins.cidrs);
  const [newCidr, setNewCidr] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [scale, setScale] = useState(e.scale);
  const [alerts, setAlerts] = useState({ latency_p95_ms: app.alerts?.latency_p95_ms ?? 1500, error_rate_pct: app.alerts?.error_rate_pct ?? 2 });
  const [backup, setBackup] = useState({ nightly_utc: app.backup?.nightly_utc ?? "06:00", pitr_retention_days: app.backup?.pitr_retention_days ?? 7 });
  const [tenants, setTenants] = useState<string[]>(app.auth.allowed_tenants);
  const [newTenant, setNewTenant] = useState("");
  const [subId, setSubId] = useState("");
  const [formError, setFormError] = useState("");

  function open(which: Editor, startOn?: boolean) {
    setFormError("");
    setOriginsOn(startOn ?? e.origins.enabled);
    setCidrs(e.origins.cidrs);
    setNewCidr("");
    setNewLabel("");
    setScale(e.scale);
    setAlerts({ latency_p95_ms: app.alerts?.latency_p95_ms ?? 1500, error_rate_pct: app.alerts?.error_rate_pct ?? 2 });
    setBackup({ nightly_utc: app.backup?.nightly_utc ?? "06:00", pitr_retention_days: app.backup?.pitr_retention_days ?? 7 });
    setTenants(app.auth.allowed_tenants);
    setNewTenant("");
    setSubId("");
    setEditor(which);
  }

  function finish(r: ActionResult) {
    if (r.ok) {
      setEditor(null);
      setSnack({ text: r.message, href: r.href });
      router.refresh();
    } else {
      setFormError(r.error);
    }
  }

  function submit(title: string, patch: object) {
    start(async () => finish(await proposeChange({ title, file: path, patch })));
  }

  function addCidr() {
    if (!validCidr(newCidr)) return setFormError("Enter a network like 203.0.113.0/24.");
    if (!newLabel.trim()) return setFormError("Give the network a label, for example Client VPN.");
    if (cidrs.some((c) => c.cidr === newCidr.trim())) return setFormError("That network is already listed.");
    setCidrs([...cidrs, { cidr: newCidr.trim(), label: newLabel.trim() }]);
    setNewCidr("");
    setNewLabel("");
    setFormError("");
  }

  function saveOrigins() {
    if (originsOn && cidrs.length === 0) return setFormError("Add at least one client network before turning this on.");
    const verb = originsOn === e.origins.enabled ? "Update" : originsOn ? "Enable" : "Disable";
    submit(`${verb} origin restriction (${env})`, { environments: { [env]: { origins: { enabled: originsOn, cidrs } } } });
  }

  function saveScale() {
    if (scale.min < 0 || scale.max < 1 || scale.min > scale.max || scale.max > 10) return setFormError("Use 0 to 10 replicas, with min no higher than max.");
    submit(`Change scaling (${env}) to ${scale.min} to ${scale.max}`, { environments: { [env]: { scale } } });
  }

  function saveAlerts() {
    if (alerts.latency_p95_ms < 100 || alerts.error_rate_pct < 0 || alerts.error_rate_pct > 100) return setFormError("Latency must be at least 100 ms and error rate between 0 and 100%.");
    submit("Change alert thresholds", { alerts });
  }

  function saveBackup() {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(backup.nightly_utc)) return setFormError("Use a 24-hour UTC time like 06:00.");
    if (backup.pitr_retention_days < 7 || backup.pitr_retention_days > 35) return setFormError("Point-in-time retention must be 7 to 35 days.");
    submit("Change backup schedule", { backup });
  }

  function saveTenants() {
    if (tenants.length === 0) return setFormError("Keep at least one tenant.");
    submit("Change sign-in tenants", { auth: { allowed_tenants: tenants } });
  }

  function saveGraduate() {
    start(async () => finish(await graduateApp(app.id, subId)));
  }

  const busy = pending;
  const disabledNote = !isAdmin ? <div className="helper">Read only: your account does not have the Admin role.</div> : null;

  return (
    <>
      {app.stage === "incubating" && app.client_data && (
        <div className="banner warn" style={{ marginTop: 12 }}>
          <Icon n="warning" />
          <div>This app is marked as holding real client data, but it still runs on the shared sandbox server. Graduate it before go-live.</div>
        </div>
      )}
      {app.stage === "incubating" && (
        <div className="card outlined" style={{ marginTop: 12 }}>
          <div className="spread">
            <div>
              <div className="title-s">Incubating in the shared sandbox</div>
              <div className="body-m muted">Graduating moves it to the client&apos;s own subscription and Postgres servers.</div>
            </div>
          </div>
          <div className="actions" style={{ marginTop: 12 }}>
            <button className="btn filled" onClick={() => open("graduate")} disabled={!isAdmin}><Icon n="school" />Graduate</button>
          </div>
        </div>
      )}

      <div className="section-label">Configuration</div>
      <div className="list">
        <button className="set" onClick={() => open("origins", !e.origins.enabled)} disabled={!isAdmin}>
          <Icon n="public" className="ico" />
          <span className="txt">
            <span className="h">Origin restriction <Lock show={prodOrApproval(`environments.${env}.origins`)} /></span>
            <span className="s" style={{ display: "block" }}>
              {e.origins.enabled
                ? `On. ${e.origins.cidrs.length} client network${e.origins.cidrs.length === 1 ? "" : "s"} allowed`
                : "Off. Anyone can reach the sign-in page"}
            </span>
          </span>
          <span className={`switch ${e.origins.enabled ? "on" : ""}`} role="switch" aria-checked={e.origins.enabled} aria-label="Origin restriction" />
        </button>
        <button className="set" onClick={() => open("tenants")} disabled={!isAdmin}>
          <Icon n="badge" className="ico" />
          <span className="txt">
            <span className="h">Sign-in tenants <Lock show={prodOrApproval("auth.allowed_tenants")} /></span>
            <span className="s" style={{ display: "block" }}>
              {app.auth.allowed_tenants.length} tenant{app.auth.allowed_tenants.length === 1 ? "" : "s"} · {app.auth.consent_granted ? "consent granted" : "consent not granted yet"}
            </span>
          </span>
          <Icon n="chevron_right" className="muted" />
        </button>
        <button className="set" onClick={() => open("scale")} disabled={!isAdmin}>
          <Icon n="stacks" className="ico" />
          <span className="txt">
            <span className="h">Scaling <Lock show={prodOrApproval(`environments.${env}.scale`)} /></span>
            <span className="s" style={{ display: "block" }}>Min {e.scale.min} · Max {e.scale.max} replicas</span>
          </span>
          <Icon n="chevron_right" className="muted" />
        </button>
        <button className="set" onClick={() => open("alerts")} disabled={!isAdmin}>
          <Icon n="speed" className="ico" />
          <span className="txt">
            <span className="h">Alert thresholds <Lock show={prodOrApproval("alerts")} /></span>
            <span className="s" style={{ display: "block" }}>
              p95 over {(app.alerts?.latency_p95_ms ?? 1500).toLocaleString("en-US")} ms · errors over {app.alerts?.error_rate_pct ?? 2}%
            </span>
          </span>
          <Icon n="chevron_right" className="muted" />
        </button>
        <button className="set" onClick={() => open("backup")} disabled={!isAdmin}>
          <Icon n="backup" className="ico" />
          <span className="txt">
            <span className="h">Backup schedule <Lock show={prodOrApproval("backup")} /></span>
            <span className="s" style={{ display: "block" }}>
              {app.backup?.nightly_utc ? `Nightly ${app.backup.nightly_utc} UTC · ` : app.stage === "incubating" ? "Sandbox: no nightly dump · " : ""}
              PITR {app.backup?.pitr_retention_days ?? 7} days
            </span>
          </span>
          <Icon n="chevron_right" className="muted" />
        </button>
      </div>
      {disabledNote}

      <Sheet open={editor === "origins"} onClose={() => setEditor(null)} label="Origin restriction">
        <div className="spread">
          <h2>Origin restriction</h2>
          <button className={`switch ${originsOn ? "on" : ""}`} role="switch" aria-checked={originsOn} aria-label="Turn origin restriction on or off" onClick={() => setOriginsOn(!originsOn)} />
        </div>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>
          {originsOn
            ? `Only these networks can reach the ${ENV_LABEL[env].toLowerCase()} frontend. Everything else gets a 403.`
            : `Off. Anyone on the internet can reach the ${ENV_LABEL[env].toLowerCase()} sign-in page.`}
        </p>
        <div className="label-l" style={{ marginBottom: 4 }}>Allowed networks</div>
        {cidrs.map((c) => (
          <div className="cidr" key={c.cidr}>
            <Icon n="lan" className="muted" />
            <div className="txt"><div className="ip">{c.cidr}</div><div className="d">{c.label}</div></div>
            <button className="icon-btn" style={{ width: 40, height: 40 }} aria-label={`Remove ${c.cidr}`} onClick={() => setCidrs(cidrs.filter((x) => x.cidr !== c.cidr))}>
              <Icon n="close" />
            </button>
          </div>
        ))}
        {lockedOrigins.map((c) => (
          <div className="cidr" key={c.cidr}>
            <Icon n={c.cidr.includes("/") ? "home" : "monitor_heart"} className="" />
            <div className="txt">
              <div className="ip" style={c.cidr.includes("/") ? undefined : { fontFamily: "Roboto, sans-serif" }}>{c.cidr.includes("/") ? c.cidr : "Availability test ranges"}</div>
              <div className="d">{c.label}</div>
            </div>
            <Icon n="lock" className="muted" />
          </div>
        ))}
        <label className="field" style={{ marginTop: 16 }}>
          <span className="lab">Add network (CIDR)</span>
          <input className="mono" value={newCidr} onChange={(ev) => setNewCidr(ev.target.value)} placeholder="203.0.113.0/24" inputMode="decimal" />
        </label>
        <div className="row" style={{ marginTop: 12, alignItems: "flex-start" }}>
          <label className="field grow" style={{ marginTop: 0 }}>
            <span className="lab">Label</span>
            <input value={newLabel} onChange={(ev) => setNewLabel(ev.target.value)} placeholder="Client VPN" maxLength={60} />
          </label>
          <button className="btn tonal" style={{ height: 56, borderRadius: 16 }} onClick={addCidr}><Icon n="add" />Add</button>
        </div>
        {formError && <div className="helper err">{formError}</div>}
        {(needsApproval(approvalFields, `environments.${env}.origins`)) && (
          <div className="banner warn" style={{ marginTop: 16 }}>
            <Icon n="approval" />
            <div>Security change. Saving opens a pull request that needs your approval with MFA before it applies.</div>
          </div>
        )}
        <div className="actions">
          <button className="btn text" onClick={() => setEditor(null)}>Cancel</button>
          <button className="btn filled" onClick={saveOrigins} disabled={busy}>
            <Icon n={busy ? "progress_activity" : "send"} />
            {needsApproval(approvalFields, `environments.${env}.origins`) ? "Submit for approval" : "Save"}
          </button>
        </div>
      </Sheet>

      <Sheet open={editor === "scale"} onClose={() => setEditor(null)} label="Scaling">
        <h2>Scaling · {ENV_LABEL[env]}</h2>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>Replicas for both the frontend and backend containers. 0 lets the app sleep when idle.</p>
        <div className="row">
          <label className="field grow"><span className="lab">Min replicas</span>
            <input type="number" min={0} max={10} value={scale.min} onChange={(ev) => setScale({ ...scale, min: Number(ev.target.value) })} />
          </label>
          <label className="field grow"><span className="lab">Max replicas</span>
            <input type="number" min={1} max={10} value={scale.max} onChange={(ev) => setScale({ ...scale, max: Number(ev.target.value) })} />
          </label>
        </div>
        {formError && <div className="helper err">{formError}</div>}
        <SaveRow busy={busy} approval={needsApproval(approvalFields, `environments.${env}.scale`)} onCancel={() => setEditor(null)} onSave={saveScale} />
      </Sheet>

      <Sheet open={editor === "alerts"} onClose={() => setEditor(null)} label="Alert thresholds">
        <h2>Alert thresholds</h2>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>Applies to all environments of this app. Breaches go to the daily digest as P2.</p>
        <label className="field"><span className="lab">p95 latency (ms)</span>
          <input type="number" min={100} step={100} value={alerts.latency_p95_ms} onChange={(ev) => setAlerts({ ...alerts, latency_p95_ms: Number(ev.target.value) })} />
        </label>
        <label className="field" style={{ marginTop: 16 }}><span className="lab">Error rate (%)</span>
          <input type="number" min={0} max={100} step={0.5} value={alerts.error_rate_pct} onChange={(ev) => setAlerts({ ...alerts, error_rate_pct: Number(ev.target.value) })} />
        </label>
        {formError && <div className="helper err">{formError}</div>}
        <SaveRow busy={busy} approval={needsApproval(approvalFields, "alerts")} onCancel={() => setEditor(null)} onSave={saveAlerts} />
      </Sheet>

      <Sheet open={editor === "backup"} onClose={() => setEditor(null)} label="Backup schedule">
        <h2>Backup schedule</h2>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>Nightly dumps go to immutable storage and the Mac Mini. Point-in-time restore is built into Postgres.</p>
        <label className="field"><span className="lab">Nightly dump time (UTC)</span>
          <input value={backup.nightly_utc} onChange={(ev) => setBackup({ ...backup, nightly_utc: ev.target.value })} placeholder="06:00" />
        </label>
        <label className="field" style={{ marginTop: 16 }}><span className="lab">Point-in-time retention (days)</span>
          <input type="number" min={7} max={35} value={backup.pitr_retention_days} onChange={(ev) => setBackup({ ...backup, pitr_retention_days: Number(ev.target.value) })} />
        </label>
        <div className="helper">7 to 35 days.</div>
        {formError && <div className="helper err">{formError}</div>}
        <SaveRow busy={busy} approval={needsApproval(approvalFields, "backup")} onCancel={() => setEditor(null)} onSave={saveBackup} />
      </Sheet>

      <Sheet open={editor === "tenants"} onClose={() => setEditor(null)} label="Sign-in tenants">
        <h2>Sign-in tenants</h2>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>Only staff from these Entra tenants can sign in. The backend rejects tokens from any other tenant.</p>
        {tenants.map((t) => (
          <div className="cidr" key={t}>
            <Icon n="domain" className="muted" />
            <div className="txt"><div className="ip" style={{ fontSize: 13 }}>{t}</div></div>
            <button className="icon-btn" style={{ width: 40, height: 40 }} aria-label={`Remove ${t}`} onClick={() => setTenants(tenants.filter((x) => x !== t))}><Icon n="close" /></button>
          </div>
        ))}
        <div className="row" style={{ marginTop: 12, alignItems: "flex-start" }}>
          <label className="field grow" style={{ marginTop: 0 }}><span className="lab">Tenant ID</span>
            <input className="mono" value={newTenant} onChange={(ev) => setNewTenant(ev.target.value)} placeholder="00000000-0000-0000-0000-000000000000" />
          </label>
          <button className="btn tonal" style={{ height: 56, borderRadius: 16 }} onClick={() => {
            if (!GUID_RE.test(newTenant.trim())) return setFormError("Enter a tenant ID (a GUID).");
            if (!tenants.includes(newTenant.trim())) setTenants([...tenants, newTenant.trim()]);
            setNewTenant("");
            setFormError("");
          }}><Icon n="add" />Add</button>
        </div>
        {formError && <div className="helper err">{formError}</div>}
        <SaveRow busy={busy} approval={needsApproval(approvalFields, "auth.allowed_tenants")} onCancel={() => setEditor(null)} onSave={saveTenants} />
      </Sheet>

      <Sheet open={editor === "graduate"} onClose={() => setEditor(null)} label="Graduate app">
        <h2>Graduate {app.name}</h2>
        <p className="body-m muted" style={{ margin: "4px 0 16px" }}>
          Creates the client&apos;s Postgres servers and redeploys the same images into the client subscription. The app&apos;s sandbox databases are deleted afterwards.
        </p>
        <label className="field"><span className="lab">Client subscription ID</span>
          <input className="mono" value={subId} onChange={(ev) => setSubId(ev.target.value)} placeholder="00000000-0000-0000-0000-000000000000" />
        </label>
        <div className="helper">Create sub-{app.client} under the BluFire management group first.</div>
        {formError && <div className="helper err">{formError}</div>}
        <div className="banner warn" style={{ marginTop: 16 }}>
          <Icon n="approval" />
          <div>Graduation opens a pull request that needs your approval with MFA.</div>
        </div>
        <div className="actions">
          <button className="btn text" onClick={() => setEditor(null)}>Cancel</button>
          <button className="btn filled" onClick={saveGraduate} disabled={busy}><Icon n={busy ? "progress_activity" : "school"} />Submit for approval</button>
        </div>
      </Sheet>

      <Snackbar snack={snack} onClose={() => setSnack(null)} />
    </>
  );
}

function SaveRow({ busy, approval, onCancel, onSave }: { busy: boolean; approval: boolean; onCancel: () => void; onSave: () => void }) {
  return (
    <>
      {approval && (
        <div className="banner warn" style={{ marginTop: 16 }}>
          <Icon n="approval" />
          <div>This change needs your approval with MFA before it applies.</div>
        </div>
      )}
      <div className="actions">
        <button className="btn text" onClick={onCancel}>Cancel</button>
        <button className="btn filled" onClick={onSave} disabled={busy}>
          <Icon n={busy ? "progress_activity" : approval ? "send" : "check"} />
          {approval ? "Submit for approval" : "Save"}
        </button>
      </div>
    </>
  );
}
