"""Scheduled worker jobs. Each pulls from Azure or GitHub into the state DB, or starts db-ops jobs.

Alerting never depends on these jobs: Azure Monitor and Sentinel page directly. These jobs feed the UI, the
digest and Claude, and the off-cloud heartbeat watches that they keep running.
"""

from __future__ import annotations

import logging
import secrets as pysecrets
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import digest as dg
from .. import drift as dr
from ..context import Context
from ..models import (
    Backup,
    Change,
    Cost,
    Deployment,
    Drift,
    EnvStatus,
    Finding,
    Incident,
    Operation,
    RestoreTest,
    SecretMeta,
    now,
)
from ..naming import app_env
from ..registry import ENVS, Snapshot
from ..telemetry import event

log = logging.getLogger("blufire.worker")
SEVERITY = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "MODERATE": "medium"}


def _ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt and not dt.tzinfo else dt


def _envs(snap: Snapshot):
    """Every (app, env, names) that should exist in Azure."""
    for app in snap.apps.values():
        if app["stage"] == "graduated" and not snap.clients.get(app["client"], {}).get("subscription_id"):
            continue
        for env in ENVS:
            yield app, env, app_env(app, env, snap.platform, snap.clients)


# ---------------------------------------------------------------- pure transforms (unit tested)
def health(env_cfg: dict, alerts: dict, metrics: dict | None, replicas: int | None) -> tuple[str, str]:
    images = env_cfg.get("images") or {}
    if not any(images.values()):
        return "not_deployed", "Not deployed"
    if replicas == 0 and env_cfg["scale"]["min"] == 0:
        return "scaled_to_zero", "Scaled to 0"
    if not metrics:
        return "unknown", "No telemetry yet"
    if metrics.get("last_availability_ok") is False:
        return "down", "Availability test failing"
    p95, err = metrics.get("p95_ms"), metrics.get("error_rate_pct")
    if (p95 and p95 > alerts["latency_p95_ms"]) or (err and err > alerts["error_rate_pct"]):
        return "degraded", f"p95 {p95:.0f} ms, errors {err:.1f}%"
    avail = metrics.get("availability_pct")
    return "healthy", f"Up {avail:.2f}%" if avail is not None else "Healthy"


def trivy_findings(app: str, env: str, report: dict, sla: dict, seen: datetime) -> list[Finding]:
    out = []
    for result in report.get("Results", []) or []:
        for v in result.get("Vulnerabilities", []) or []:
            sev = SEVERITY.get(v.get("Severity", ""), "low")
            if sev == "low":
                continue
            out.append(
                Finding(
                    id=f"trivy/{app}/{env}/{v['VulnerabilityID']}/{v.get('PkgName', '')}",
                    source="trivy",
                    app=app,
                    env=env,
                    title=f"{v.get('PkgName')} {v.get('InstalledVersion', '')}".strip()
                    + (f", fixed in {v['FixedVersion']}" if v.get("FixedVersion") else ""),
                    package=v.get("PkgName"),
                    cve=v["VulnerabilityID"],
                    severity=sev,
                    link=v.get("PrimaryURL"),
                    due_at=seen + timedelta(days=sla.get(sev, 90)),
                )
            )
    return out


def eol_findings(snap: Snapshot, today: date) -> list[Finding]:
    out = []
    for app_id, app in snap.apps.items():
        for runtime, eol in (app.get("stack", {}).get("runtime_eol") or {}).items():
            eol_date = date.fromisoformat(eol)
            days = (eol_date - today).days
            if days <= 90:
                out.append(
                    Finding(
                        id=f"runtime_eol/{app_id}/{runtime}",
                        source="runtime_eol",
                        app=app_id,
                        title=f"{runtime} end of life {'passed' if days < 0 else f'in {days} days'}",
                        package=runtime,
                        severity="high" if days < 30 else "medium",
                        due_at=datetime.combine(eol_date, datetime.min.time(), UTC),
                    )
                )
    return out


def upsert_findings(
    s: Session, source: str, fresh: list[Finding], scope_app: str | None = None, scope_env: str | None = None
):
    """Insert new findings, refresh existing ones, resolve those that disappeared from the source."""
    seen_ids = set()
    for f in fresh:
        seen_ids.add(f.id)
        row = s.get(Finding, f.id)
        if row:
            row.last_seen, row.title, row.severity = now(), f.title, f.severity
            if row.status == "resolved" and not (row.note or "").startswith("False positive"):
                row.status = "open"
        else:
            s.add(f)
    q = select(Finding).where(Finding.source == source, Finding.status != "resolved")
    if scope_app:
        q = q.where(Finding.app == scope_app)
    if scope_env:
        q = q.where(Finding.env == scope_env)
    for row in s.scalars(q):
        if row.id not in seen_ids:
            row.status = "resolved"


def incident_from_row(r: dict) -> Incident:
    sev = {"High": "p1", "Medium": "p2"}.get(r.get("Severity"), "p3")
    return Incident(
        id=f"sentinel/{r['IncidentNumber']}",
        source="sentinel",
        severity=sev,
        title=r.get("Title", "Sentinel incident"),
        status="closed" if r.get("Status") == "Closed" else "open",
        opened_at=_ts(r.get("CreatedTime")) or now(),
        closed_at=_ts(r.get("ClosedTime")),
        link=r.get("IncidentUrl"),
    )


def ingest_dbops_result(s: Session, blob: str, data: dict) -> None:
    """dbops-results/<app>/<env>/<kind>/<ts>.json, written by blufire-dbops."""
    kind = data.get("kind")
    if kind == "dump" and not s.get(Backup, blob):
        s.add(
            Backup(
                id=blob,
                app=data["app"],
                env=data["env"],
                layer=data.get("layer", "nightly"),
                location=data.get("blob", ""),
                size_bytes=data.get("size_bytes"),
                checksum=data.get("sha256"),
                created_at=_ts(data.get("finished_at")) or now(),
                result="ok" if data.get("ok") else "failed",
            )
        )
        if not data.get("ok"):
            event("backup_failed", app=data["app"], env=data["env"], detail=data.get("detail", ""))
    elif kind == "restore_test" and not s.get(RestoreTest, blob):
        s.add(
            RestoreTest(
                id=blob,
                app=data["app"],
                backup_id=data.get("source_blob", ""),
                started_at=_ts(data.get("started_at")) or now(),
                duration_s=data.get("duration_s"),
                checks=data.get("checks", []),
                result="passed" if data.get("ok") else "failed",
            )
        )
        if not data.get("ok"):
            event("restore_test_failed", app=data["app"], env=data["env"], detail=data.get("detail", ""))
    elif kind == "off_cloud" and not s.get(Backup, blob):
        s.add(
            Backup(
                id=blob,
                app=data.get("app", "all"),
                env=data.get("env", "prod"),
                layer="off_cloud",
                location=data.get("location", "M2 Mac Mini"),
                size_bytes=data.get("size_bytes"),
                checksum=None,
                created_at=_ts(data.get("finished_at")) or now(),
                result="ok" if data.get("ok") else "failed",
            )
        )


def late_backups(snap: Snapshot, s: Session, at: datetime) -> list[tuple[str, str]]:
    """Graduated prod apps with no successful nightly dump in the last 26 hours."""
    late = []
    for app in snap.apps.values():
        if app["stage"] != "graduated" or not any((app["environments"]["prod"].get("images") or {}).values()):
            continue
        last = s.scalar(
            select(Backup.created_at)
            .where(Backup.app == app["id"], Backup.env == "prod", Backup.layer == "nightly", Backup.result == "ok")
            .order_by(Backup.created_at.desc())
        )
        if not last or at - _aware(last) > timedelta(hours=26):
            late.append((app["id"], "prod"))
    return late


# ---------------------------------------------------------------- jobs
METRICS_KQL = """
let req = AppRequests | where TimeGenerated > ago(24h)
  | extend comp = tolower(tostring(split(_ResourceId, '/')[-1]))
  | summarize p95_ms = percentile(DurationMs, 95), total = count(), failed = countif(Success == false) by comp;
let av = AppAvailabilityResults | where TimeGenerated > ago(24h)
  | extend comp = tolower(tostring(split(_ResourceId, '/')[-1]))
  | summarize availability_pct = 100.0 * countif(Success == true) / count(), last = arg_max(TimeGenerated, Success) by comp
  | project comp, availability_pct, last_availability_ok = Success;
req | join kind=fullouter av on comp | project comp = coalesce(comp, comp1), p95_ms, total, failed, availability_pct, last_availability_ok
"""

INCIDENTS_KQL = """
SecurityIncident | where TimeGenerated > ago(30d)
| summarize arg_max(TimeGenerated, *) by IncidentNumber
| project IncidentNumber, Title, Severity, Status, CreatedTime, ClosedTime, IncidentUrl
"""

DEFENDER_RG = """
securityresources
| where type == 'microsoft.security/assessments' and properties.status.code == 'Unhealthy'
| project id, title = tostring(properties.displayName), severity = tolower(tostring(properties.metadata.severity)),
          resourceId = tolower(tostring(properties.resourceDetails.Id)), link = tostring(properties.links.azurePortal)
"""


def sync(ctx: Context) -> str:
    snap = ctx.snapshot(fresh=True)
    az = ctx.azure
    sla = snap.alert_defaults.get("remediation_sla_days", {})
    with ctx.sessions() as s:
        upsert_findings(s, "runtime_eol", eol_findings(snap, date.today()))
        s.commit()
        if az is None:
            return "dev mode: Azure sync skipped"

        ws = _settings().log_analytics_workspace_id
        metrics = {r["comp"]: r for r in az.log_query(ws, METRICS_KQL)} if ws else {}
        for app, env, n in _envs(snap):
            replicas, release = None, app["environments"][env].get("release")
            try:
                revs = az.revisions(n.subscription, n.resource_group, n.frontend)
                active = [r for r in revs if r["properties"].get("active")]
                replicas = sum(r["properties"].get("replicas", 0) for r in active)
                for r in revs:
                    _record_deployment(s, app["id"], env, "frontend", r, release)
                for r in az.revisions(n.subscription, n.resource_group, n.backend):
                    _record_deployment(s, app["id"], env, "backend", r, release)
            except FileNotFoundError:
                pass
            m = metrics.get(n.app_insights.lower())
            if m and m.get("total"):
                m["error_rate_pct"] = 100.0 * (m.get("failed") or 0) / m["total"]
            alerts = {**snap.alert_defaults.get("app_alerts", {}), **(app.get("alerts") or {})}
            h, summary = health(app["environments"][env], alerts, m, replicas)
            row = s.get(EnvStatus, (app["id"], env)) or EnvStatus(app=app["id"], env=env)
            row.health, row.summary, row.release, row.updated_at = h, summary, release, now()
            row.p95_ms = (m or {}).get("p95_ms")
            row.error_rate_pct = (m or {}).get("error_rate_pct")
            row.replicas_current, row.replicas_max = replicas, app["environments"][env]["scale"]["max"]
            s.merge(row)
        s.commit()

        if ws:
            for r in az.log_query(ws, INCIDENTS_KQL, timespan="P30D"):
                s.merge(incident_from_row(r))
            s.commit()

        subs = [snap.platform["subscriptions"][k] for k in ("platform", "sandbox", "backup")]
        subs += [c["subscription_id"] for c in snap.clients.values() if c.get("subscription_id")]
        rg_to_app = {n.resource_group.lower(): (app["id"], env) for app, env, n in _envs(snap)}
        defender = []
        for r in az.resource_graph(DEFENDER_RG, subs):
            rg = (
                r["resourceId"].split("/resourcegroups/")[-1].split("/")[0]
                if "/resourcegroups/" in r["resourceId"]
                else ""
            )
            app_id, env = rg_to_app.get(rg, (None, None))
            sev = {"high": "high", "medium": "medium"}.get(r["severity"], "low")
            defender.append(
                Finding(
                    id=f"defender/{r['id']}"[:200],
                    source="defender",
                    app=app_id,
                    env=env,
                    title=r["title"],
                    severity=sev,
                    link=r["link"],
                    due_at=now() + timedelta(days=sla.get(sev, 90)),
                )
            )
        upsert_findings(s, "defender", defender)

        for app in snap.apps.values():
            alerts = ctx.store.dependabot_alerts(app["repo"])
            fresh = [
                Finding(
                    id=f"dependabot/{app['repo']}/{a['number']}",
                    source="dependabot",
                    app=app["id"],
                    title=a["security_advisory"]["summary"],
                    package=a["dependency"]["package"]["name"],
                    cve=a["security_advisory"].get("cve_id"),
                    severity=SEVERITY.get(a["security_advisory"]["severity"].upper(), "low"),
                    link=a["html_url"],
                    due_at=now()
                    + timedelta(days=sla.get(SEVERITY.get(a["security_advisory"]["severity"].upper(), "low"), 90)),
                )
                for a in alerts
            ]
            upsert_findings(s, "dependabot", fresh, scope_app=app["id"])

        latest: dict[tuple[str, str], tuple[str, dict]] = {}
        for name, report in az.list_json_blobs("scan-results"):
            parts = name.split("/")
            if len(parts) == 3:
                key = (parts[0], parts[1])
                if key not in latest or name > latest[key][0]:
                    latest[key] = (name, report)
        for (app_id, env), (_, report) in latest.items():
            upsert_findings(
                s, "trivy", trivy_findings(app_id, env, report, sla, now()), scope_app=app_id, scope_env=env
            )
        s.commit()

        for name, data in az.list_json_blobs("dbops-results"):
            ingest_dbops_result(s, name, data)
        s.commit()

        _sync_secrets(ctx, snap, s)
        month = datetime.now(UTC).strftime("%Y-%m")
        for cid, c in snap.clients.items():
            if c.get("subscription_id"):
                s.merge(Cost(month=month, client=cid, usd=az.cost_month_to_date(c["subscription_id"])))
        blufire = sum(
            az.cost_month_to_date(snap.platform["subscriptions"][k]) for k in ("platform", "sandbox", "backup")
        )
        s.merge(Cost(month=month, client="blufire", usd=blufire))
        s.commit()
    return "synced"


def _record_deployment(s: Session, app: str, env: str, component: str, rev: dict, release: str | None) -> None:
    p = rev["properties"]
    row = s.get(Deployment, rev["name"])
    result = (
        "succeeded"
        if p.get("healthState") == "Healthy"
        else "failed"
        if p.get("provisioningState") == "Failed"
        else "running"
    )
    if row:
        row.result = result if row.result != "rolled_back" else row.result
        return
    s.add(
        Deployment(
            id=rev["name"],
            app=app,
            env=env,
            component=component,
            release=release,
            image_digest=(p.get("template", {}).get("containers") or [{}])[0].get("image", ""),
            started_at=_ts(p.get("createdTime")) or now(),
            finished_at=_ts(p.get("lastActiveTime")),
            result=result,
        )
    )


def _sync_secrets(ctx: Context, snap: Snapshot, s: Session) -> None:
    cache: dict[str, dict[str, dict]] = {}
    for app, env, n in _envs(snap):
        vault = n.key_vault
        if vault not in cache:
            try:
                cache[vault] = {m["name"]: m for m in ctx.azure.list_secret_meta(vault)}
            except Exception:
                log.exception("cannot list secrets in %s", vault)
                cache[vault] = {}
        for name in app["environments"][env].get("secrets") or []:
            meta = cache[vault].get(name, {})
            s.merge(
                SecretMeta(
                    id=f"{vault}/{name}",
                    vault=vault,
                    name=name,
                    app=app["id"],
                    env=env,
                    last_rotated=_ts(meta.get("updated")),
                    expires=_ts(meta.get("exp")),
                )
            )
    s.commit()


def drift_check(ctx: Context) -> str:
    snap = ctx.snapshot(fresh=True)
    if ctx.azure is None:
        return "dev mode: drift check skipped"
    admin_ip = snap.platform["network"]["admin_static_ip"]
    extra = snap.alert_defaults.get("availability_test", {}).get("cidrs", [])
    found = 0
    with ctx.sessions() as s:
        for app, env, n in _envs(snap):
            for component, name in (("frontend", n.frontend), ("backend", n.backend)):
                try:
                    live = ctx.azure.container_app(n.subscription, n.resource_group, name)
                except FileNotFoundError:
                    continue
                items = dr.compare(name, component, app["environments"][env], live, admin_ip, extra)
                current = {f"{i.resource}|{i.property}" for i in items}
                for i in items:
                    key = f"{i.resource}|{i.property}"
                    row = s.get(Drift, key)
                    if row and row.status == "open":
                        row.live = i.live
                        continue
                    s.merge(
                        Drift(
                            id=key,
                            app=app["id"],
                            env=env,
                            resource=i.resource,
                            property=i.property,
                            desired=i.desired,
                            live=i.live,
                            status="open",
                            detected_at=now(),
                        )
                    )
                    found += 1
                    if env == "prod":
                        event("drift_detected_prod", app=app["id"], env=env, detail=f"{i.property}: {i.live}")
                for row in s.scalars(select(Drift).where(Drift.resource == name, Drift.status == "open")):
                    if row.id not in current:
                        row.status = "reverted"
        s.commit()
    return f"{found} new drift item(s)"


def _start_dbops(ctx: Context, snap: Snapshot, app: dict, env: str, args: list[str]) -> str:
    n = app_env(app, env, snap.platform, snap.clients)
    return ctx.azure.start_job(n.subscription, n.shared_resource_group, n.dbops_job, args)


def nightly_backup(ctx: Context) -> str:
    snap = ctx.snapshot(fresh=True)
    if ctx.azure is None:
        return "dev mode: backups skipped"
    started = 0
    for app in snap.apps.values():
        if app["stage"] != "graduated" or not any((app["environments"]["prod"].get("images") or {}).values()):
            continue
        n = app_env(app, "prod", snap.platform, snap.clients)
        _start_dbops(
            ctx,
            snap,
            app,
            "prod",
            ["dump", "--app", app["id"], "--env", "prod", "--database", n.database, "--layer", "nightly"],
        )
        started += 1
    plat = snap.platform["subscriptions"]["platform"]
    ctx.azure.start_job(
        plat,
        "rg-platform-prod",
        "caj-platform-dbops",
        ["dump", "--app", "platform", "--env", "prod", "--database", "blufire", "--layer", "nightly"],
    )
    with ctx.sessions() as s:
        for app_id, env in late_backups(snap, s, datetime.now(UTC)):
            event("backup_failed", app=app_id, env=env, detail="no successful nightly dump in 26 hours")
        _cleanup_graduated(ctx, snap, s)
    return f"started {started + 1} dump job(s)"


def _cleanup_graduated(ctx: Context, snap: Snapshot, s: Session) -> None:
    """Drop an app's sandbox databases 14 days after its graduation PR merged."""
    cutoff = datetime.now(UTC) - timedelta(days=14)
    for c in s.scalars(select(Change).where(Change.status == "applied")):
        if "operation:graduate" not in (c.matched_rules or []) or not c.decided_at or _aware(c.decided_at) > cutoff:
            continue
        app_id = next((a for a, f in snap.app_files.items() if f == c.file), None)
        done = s.scalar(select(Operation).where(Operation.action == "sandbox_cleanup", Operation.app == app_id))
        if not app_id or done:
            continue
        app = snap.apps[app_id]
        sandbox = {**app, "stage": "incubating"}
        for env in ENVS:
            db = app_env(sandbox, env, snap.platform, snap.clients).database
            ctx.azure.start_job(
                snap.platform["subscriptions"]["sandbox"],
                "rg-sandbox-shared",
                "caj-sandbox-dbops",
                ["drop-database", "--database", db],
            )
        s.add(Operation(action="sandbox_cleanup", app=app_id, requested_by="worker", status="done", finished_at=now()))
    s.commit()


def restore_test(ctx: Context) -> str:
    snap = ctx.snapshot(fresh=True)
    if ctx.azure is None:
        return "dev mode: restore tests skipped"
    count = 0
    for app in snap.apps.values():
        if app["stage"] == "graduated" and any((app["environments"]["prod"].get("images") or {}).values()):
            n = app_env(app, "prod", snap.platform, snap.clients)
            _start_dbops(
                ctx, snap, app, "prod", ["restore-test", "--app", app["id"], "--env", "prod", "--database", n.database]
            )
            count += 1
    return f"started {count} restore test(s)"


def digest(ctx: Context) -> str:
    snap = ctx.snapshot(fresh=True)
    with ctx.sessions() as s:
        d = dg.build(snap, s)
    cfg = _settings()
    to = snap.alert_defaults.get("digest", {}).get("recipients") or [snap.platform["alerts"]["email"]]
    if not cfg.acs_endpoint:
        log.info("digest built (no ACS endpoint configured):\n%s", d["text"])
        return "digest built, not sent"
    _send_email(
        cfg.acs_endpoint, cfg.digest_sender, to, f"BluFire Ops: {len(d['p1'])} P1, {len(d['p2'])} P2", d["text"]
    )
    return f"digest sent to {len(to)} recipient(s)"


def _send_email(endpoint: str, sender: str, to: list[str], subject: str, body: str) -> None:
    import httpx
    from azure.identity import DefaultAzureCredential

    cred = DefaultAzureCredential(managed_identity_client_id=_settings().azure_client_id or None)
    token = cred.get_token("https://communication.azure.com/.default").token
    r = httpx.post(
        f"{endpoint.rstrip('/')}/emails:send",
        params={"api-version": "2023-03-31"},
        headers={"Authorization": f"Bearer {token}"},
        json={
            "senderAddress": sender,
            "content": {"subject": subject, "plainText": body},
            "recipients": {"to": [{"address": a} for a in to]},
        },
        timeout=30,
    )
    r.raise_for_status()


def ops(ctx: Context) -> str:
    """Run queued operations requested through the API."""
    handled = 0
    with ctx.sessions() as s:
        queued = s.scalars(select(Operation).where(Operation.status == "queued").order_by(Operation.created_at)).all()
        for op in queued:
            op.status = "running"
            s.commit()
            try:
                op.detail = _run_op(ctx, op)
                op.status = "done"
            except Exception as exc:  # recorded on the operation, shown in the UI and digest
                log.exception("operation %s failed", op.id)
                op.status, op.detail = "failed", str(exc)[:500]
            op.finished_at = now()
            s.commit()
            handled += 1
    return f"{handled} operation(s)"


def _run_op(ctx: Context, op: Operation) -> str:
    snap = ctx.snapshot()
    if op.action == "drift_check":
        return drift_check(ctx)
    if op.action == "digest":
        return digest(ctx)
    if op.action == "scan":
        ctx.store.dispatch_workflow("nightly-image-scan.yml")
        return "image scan workflow started"
    if op.action == "drift_revert":
        ctx.store.dispatch_workflow("apply.yml", {"app": op.app or "", "env": op.env or ""})
        return "re-apply from git started"
    if ctx.azure is None:
        return f"dev mode: {op.action} skipped"
    app = snap.app(op.app) if op.app else None
    if op.action in ("backup", "restore_test"):
        if not app or not op.env:
            raise ValueError("app and env are required")
        n = app_env(app, op.env, snap.platform, snap.clients)
        cmd = ["dump", "--layer", "manual"] if op.action == "backup" else ["restore-test"]
        return _start_dbops(
            ctx, snap, app, op.env, [*cmd, "--app", app["id"], "--env", op.env, "--database", n.database]
        )
    if op.action == "secret_rotate":
        vault, name = op.target.split("/", 1)
        ctx.azure.set_secret(vault, name, pysecrets.token_urlsafe(48))
        n = app_env(app, op.env, snap.platform, snap.clients)
        for ca in (n.frontend, n.backend):
            ctx.azure.restart_latest_revision(n.subscription, n.resource_group, ca)
        return f"rotated {name} and restarted {n.frontend}, {n.backend}"
    raise ValueError(f"unknown operation {op.action}")


def _settings():
    from ..config import settings

    return settings()


JOBS = {
    "sync": sync,
    "drift_check": drift_check,
    "ops": ops,
    "nightly_backup": nightly_backup,
    "restore_test": restore_test,
    "digest": digest,
}
