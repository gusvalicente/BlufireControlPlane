"""platform-api: every read and write for the admin UI and the MCP server. Contract: docs/api-contract.md."""

import hmac
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from .. import changes as ch
from .. import digest as dg
from .. import status as st
from ..auth import ADMIN, AGENT, DEV_ADMIN, DEV_AGENT, AuthError, Principal, principal_from_token, require_step_up
from ..config import Settings, settings
from ..context import Context, build_context
from ..models import (
    AuditEvent,
    Backup,
    Change,
    Cost,
    Deployment,
    Drift,
    Finding,
    Incident,
    Operation,
    RestoreTest,
    SecretMeta,
    WorkerRun,
)
from ..policy import approval_fields, operation_needs_approval
from ..registry import ENVS

log = logging.getLogger("blufire.api")
Env = Literal["dev", "cert", "prod"]
SAFE_OPS = {"backup", "restore_test", "scan", "drift_check", "digest"}


# ---------- request models ----------
class ChangeRequestIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    file: str
    patch: dict = Field(default_factory=dict)
    reason: str | None = None
    create: bool = False
    delete: bool = False


class RejectIn(BaseModel):
    reason: str = Field(min_length=1)


class AckIn(BaseModel):
    note: str = ""
    false_positive: bool = False


class OpIn(BaseModel):
    app: str | None = None
    env: Env | None = None


class LogQueryIn(BaseModel):
    kql: str = Field(min_length=3, max_length=4000)
    timespan: str = "P1D"


LOG_TABLES = {
    "AppRequests",
    "AppExceptions",
    "AppTraces",
    "AppDependencies",
    "AppAvailabilityResults",
    "ContainerAppConsoleLogs_CL",
    "ContainerAppSystemLogs_CL",
    "AzureActivity",
    "SecurityIncident",
    "SecurityAlert",
}
# Anything that can reach another table or workspace is refused; only single-table pipelines are allowed.
LOG_BLOCKED = (
    "union", "join", "lookup", "toscalar", "materialize", "workspace(", "app(", "cluster(", "adx(", "arg(",
    "database(", "table(", "search", "find ", "externaldata", "evaluate", "invoke", ";", "let ",
)


class GraduateIn(BaseModel):
    subscription_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")


# ---------- helpers ----------
def _row(obj) -> dict:
    out = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name)
        out[col.name] = value.isoformat() if isinstance(value, datetime) else value
    return out


def _audit(ctx: Context, p: Principal | None, request: Request, result: str) -> None:
    try:
        with ctx.sessions() as s:
            s.add(
                AuditEvent(
                    actor_kind=p.kind if p else "unknown",
                    actor=(
                        f"{p.name} via {request.headers['x-on-behalf-of']}"
                        if p and "x-on-behalf-of" in request.headers
                        else p.name
                    )
                    if p
                    else "anonymous",
                    action=f"{request.method} {request.url.path}",
                    target=request.url.path,
                    source_ip=request.headers.get("x-forwarded-for", request.client.host if request.client else None),
                    result=result,
                )
            )
            s.commit()
    except Exception:  # audit must never break the request; the log line still lands in Log Analytics
        log.exception("audit write failed")
    log.info("audit", extra={"actor": p.name if p else None, "path": request.url.path, "result": result})


def create_app(ctx: Context | None = None, cfg: Settings | None = None, signing_key=None) -> FastAPI:
    cfg = cfg or settings()
    app = FastAPI(title="BluFire platform-api", version="0.1.0", docs_url="/docs" if cfg.dev_mode else None)
    app.state.ctx = ctx or build_context()

    def get_ctx(request: Request) -> Context:
        return request.app.state.ctx

    def principal(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
        if cfg.dev_mode and not authorization:
            p = DEV_AGENT if request.headers.get("x-dev-role") == "agent" else DEV_ADMIN
        else:
            if not authorization or not authorization.lower().startswith("bearer "):
                raise AuthError(401, "missing_token", "bearer token required")
            p = principal_from_token(authorization.split(" ", 1)[1], cfg, signing_key)
        request.state.principal = p
        return p

    def admin(p: Annotated[Principal, Depends(principal)]) -> Principal:
        if ADMIN not in p.roles:
            raise AuthError(403, "forbidden", "Admin role required")
        return p

    def admin_or_agent(p: Annotated[Principal, Depends(principal)]) -> Principal:
        if not {ADMIN, AGENT} & set(p.roles):
            raise AuthError(403, "forbidden", "Admin or Agent role required")
        return p

    def step_up_admin(
        p: Annotated[Principal, Depends(admin)], x_step_up_token: Annotated[str | None, Header()] = None
    ) -> Principal:
        if not cfg.dev_mode:
            require_step_up(p, x_step_up_token, cfg, signing_key)
        return p

    Ctx = Annotated[Context, Depends(get_ctx)]
    Any_ = Annotated[Principal, Depends(principal)]
    Admin = Annotated[Principal, Depends(admin)]
    Writer = Annotated[Principal, Depends(admin_or_agent)]
    StepUp = Annotated[Principal, Depends(step_up_admin)]

    @app.middleware("http")
    async def audit_mw(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/") and request.url.path != "/api/v1/heartbeat":
            result = "ok" if response.status_code < 400 else "denied" if response.status_code in (401, 403) else "error"
            _audit(request.app.state.ctx, getattr(request.state, "principal", None), request, result)
        return response

    @app.exception_handler(AuthError)
    async def _auth_err(request: Request, exc: AuthError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(ch.ChangeError)
    async def _change_err(request: Request, exc: ch.ChangeError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(KeyError)
    async def _key_err(request: Request, exc: KeyError):
        return JSONResponse({"error": {"code": "not_found", "message": str(exc.args[0])}}, status_code=404)

    # ---------- probes ----------
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/readyz")
    def readyz(ctx: Ctx):
        with ctx.sessions() as s:
            s.execute(text("select 1"))
        return {"ok": True}

    # ---------- identity and fleet ----------
    @app.get("/api/v1/me")
    def me(p: Any_):
        return {"oid": p.oid, "name": p.name, "roles": list(p.roles), "mfa_fresh": "mfa" in p.claims.get("amr", [])}

    @app.get("/api/v1/fleet")
    def fleet(ctx: Ctx, p: Any_):
        with ctx.sessions() as s:
            return st.fleet(ctx.snapshot(), s)

    @app.get("/api/v1/clients")
    def clients(ctx: Ctx, p: Any_):
        snap = ctx.snapshot()
        return [
            {**c, "apps": sorted(a for a, doc in snap.apps.items() if doc["client"] == cid)}
            for cid, c in sorted(snap.clients.items())
        ]

    @app.get("/api/v1/apps")
    def apps(ctx: Ctx, p: Any_):
        snap = ctx.snapshot()
        with ctx.sessions() as s:
            return [st.app_summary(snap, s, a) for a in sorted(snap.apps)]

    @app.get("/api/v1/apps/{app_id}")
    def app_detail(app_id: str, ctx: Ctx, p: Any_):
        snap = ctx.snapshot()
        with ctx.sessions() as s:
            summary = st.app_summary(snap, s, app_id)
        return {
            "registry": snap.app(app_id),
            "path": snap.app_files[app_id],
            "summary": summary,
            "approval_fields": approval_fields(snap.policy),
            "admin_static_ip": snap.platform.get("network", {}).get("admin_static_ip"),
        }

    @app.get("/api/v1/apps/{app_id}/environments/{env}/runtime")
    def runtime(app_id: str, env: Env, ctx: Ctx, p: Any_):
        cfg_env = ctx.snapshot().app(app_id)["environments"][env]
        with ctx.sessions() as s:
            secrets = s.scalars(select(SecretMeta).where(SecretMeta.app == app_id, SecretMeta.env == env)).all()
        known = {m.name: m for m in secrets}
        return {
            "release": cfg_env.get("release"),
            "images": cfg_env.get("images") or {},
            "bicep_params": {k: v for k, v in cfg_env.items() if k not in ("env_vars", "secrets")},
            "env_vars": cfg_env.get("env_vars") or {},
            "secrets": [
                {
                    "name": name,
                    "last_rotated": known[name].last_rotated.isoformat()
                    if name in known and known[name].last_rotated
                    else None,
                    "expires": known[name].expires.isoformat() if name in known and known[name].expires else None,
                }
                for name in cfg_env.get("secrets") or []
            ],
        }

    # ---------- changes ----------
    @app.post("/api/v1/changes", status_code=201)
    def create_change(body: ChangeRequestIn, ctx: Ctx, p: Writer):
        change = ch.propose(ctx, ch.ChangeIn(**body.model_dump()), p)
        return ch.as_dict(change)

    @app.get("/api/v1/changes")
    def list_changes(ctx: Ctx, p: Any_, status: Literal["pending", "applied", "rejected", "failed", "all"] = "pending"):
        with ctx.sessions() as s:
            q = select(Change).order_by(Change.created_at.desc()).limit(200)
            if status != "all":
                q = q.where(Change.status == status)
            return [ch.as_dict(c) for c in s.scalars(q)]

    @app.get("/api/v1/changes/{change_id}")
    def get_change(change_id: str, ctx: Ctx, p: Any_):
        return ch.as_dict(ch.get(ctx, change_id))

    @app.post("/api/v1/changes/{change_id}/approve")
    def approve(change_id: str, ctx: Ctx, p: StepUp):
        return ch.as_dict(ch.approve(ctx, change_id, p))

    @app.post("/api/v1/changes/{change_id}/reject")
    def reject(change_id: str, body: RejectIn, ctx: Ctx, p: Admin):
        return ch.as_dict(ch.reject(ctx, change_id, p, body.reason))

    @app.post("/api/v1/apps/{app_id}/graduate", status_code=201)
    def graduate(app_id: str, body: GraduateIn, ctx: Ctx, p: Admin):
        return ch.as_dict(ch.propose_graduation(ctx, app_id, body.subscription_id, p))

    # ---------- observed state ----------
    def _list(model, ctx: Context, *filters, order=None, limit: int = 200):
        with ctx.sessions() as s:
            q = select(model).where(*filters).limit(limit)
            if order is not None:
                q = q.order_by(order)
            return [_row(r) for r in s.scalars(q)]

    @app.get("/api/v1/deployments")
    def deployments(ctx: Ctx, p: Any_, app: str | None = None, env: Env | None = None):
        f = [
            c for c in (Deployment.app == app if app else None, Deployment.env == env if env else None) if c is not None
        ]
        return _list(Deployment, ctx, *f, order=Deployment.started_at.desc())

    @app.get("/api/v1/backups")
    def backups(ctx: Ctx, p: Any_, app: str | None = None, env: Env | None = None):
        f = [c for c in (Backup.app == app if app else None, Backup.env == env if env else None) if c is not None]
        return _list(Backup, ctx, *f, order=Backup.created_at.desc())

    @app.get("/api/v1/restore-tests")
    def restore_tests(ctx: Ctx, p: Any_, app: str | None = None):
        f = [RestoreTest.app == app] if app else []
        return _list(RestoreTest, ctx, *f, order=RestoreTest.started_at.desc())

    @app.get("/api/v1/findings")
    def findings(ctx: Ctx, p: Any_, status: Literal["open", "resolved", "all"] = "open", severity: str | None = None):
        f = []
        if status == "open":
            f.append(Finding.status.in_(["open", "acknowledged"]))
        elif status == "resolved":
            f.append(Finding.status == "resolved")
        if severity:
            f.append(Finding.severity == severity)
        return _list(Finding, ctx, *f, order=Finding.first_seen.desc(), limit=500)

    @app.post("/api/v1/findings/{finding_id:path}/ack")
    def ack(finding_id: str, body: AckIn, ctx: Ctx, p: Admin):
        with ctx.sessions() as s:
            f = s.get(Finding, finding_id)
            if not f:
                raise HTTPException(404, "finding not found")
            f.status = "resolved" if body.false_positive else "acknowledged"
            f.note = f"{'False positive. ' if body.false_positive else ''}{body.note} ({p.name})".strip()
            s.commit()
            return _row(f)

    @app.get("/api/v1/incidents")
    def incidents(ctx: Ctx, p: Any_, status: Literal["open", "closed", "all"] = "open"):
        f = [] if status == "all" else [Incident.status == status]
        return _list(Incident, ctx, *f, order=Incident.opened_at.desc())

    @app.get("/api/v1/drift")
    def drift(ctx: Ctx, p: Any_, status: Literal["open", "resolved", "all"] = "open"):
        f = [] if status == "all" else [Drift.status == "open"] if status == "open" else [Drift.status != "open"]
        return _list(Drift, ctx, *f, order=Drift.detected_at.desc())

    @app.post("/api/v1/drift/{drift_id:path}/adopt", status_code=201)
    def adopt(drift_id: str, ctx: Ctx, p: Writer):
        return ch.as_dict(ch.propose_drift_adoption(ctx, drift_id, p))

    @app.post("/api/v1/drift/{drift_id:path}/revert", status_code=202)
    def revert(drift_id: str, ctx: Ctx, p: Writer):
        with ctx.sessions() as s:
            d = s.get(Drift, drift_id)
            if not d:
                raise HTTPException(404, "drift item not found")
            needs = d.env == "prod" and operation_needs_approval(ctx.snapshot().policy, "drift_revert_prod")
            if needs and ADMIN not in p.roles:
                raise AuthError(403, "approval_required", "reverting prod drift needs Gus's approval in the UI")
            op = Operation(action="drift_revert", app=d.app, env=d.env, target=drift_id, requested_by=p.name)
            s.add(op)
            s.commit()
            return {"operation_id": op.id}

    @app.get("/api/v1/secrets")
    def secrets(ctx: Ctx, p: Any_, app: str | None = None, env: Env | None = None):
        f = [
            c for c in (SecretMeta.app == app if app else None, SecretMeta.env == env if env else None) if c is not None
        ]
        return _list(SecretMeta, ctx, *f, order=SecretMeta.name)

    @app.post("/api/v1/secrets/{secret_id:path}/rotate", status_code=202)
    def rotate(secret_id: str, ctx: Ctx, p: StepUp):
        with ctx.sessions() as s:
            m = s.get(SecretMeta, secret_id)
            if not m:
                raise HTTPException(404, "secret not found")
            op = Operation(action="secret_rotate", app=m.app, env=m.env, target=secret_id, requested_by=p.name)
            s.add(op)
            s.commit()
            return {"operation_id": op.id}

    @app.get("/api/v1/costs")
    def costs(ctx: Ctx, p: Any_, month: str | None = None):
        month = month or datetime.now(UTC).strftime("%Y-%m")
        rows = _list(Cost, ctx, Cost.month == month)
        return {
            "month": month,
            "total_usd": round(sum(r["usd"] for r in rows), 2),
            "by_client": [{"client": r["client"], "usd": r["usd"]} for r in rows],
        }

    @app.get("/api/v1/audit")
    def audit(ctx: Ctx, p: Any_, limit: int = 100, before: str | None = None):
        f = [AuditEvent.at < datetime.fromisoformat(before)] if before else []
        return _list(AuditEvent, ctx, *f, order=AuditEvent.at.desc(), limit=min(limit, 500))

    @app.get("/api/v1/digest/latest")
    def digest(ctx: Ctx, p: Any_):
        with ctx.sessions() as s:
            return dg.build(ctx.snapshot(), s)

    @app.post("/api/v1/logs/query")
    def logs_query(body: LogQueryIn, ctx: Ctx, p: Writer):
        first = body.kql.strip().split("|", 1)[0].strip()
        lowered = body.kql.lower()
        if first not in LOG_TABLES or any(b in lowered for b in LOG_BLOCKED):
            raise HTTPException(400, f"query must start with one of {sorted(LOG_TABLES)} and not cross workspaces")
        if ctx.azure is None or not cfg.log_analytics_workspace_id:
            return {"rows": [], "note": "no Log Analytics workspace configured"}
        rows = ctx.azure.log_query(cfg.log_analytics_workspace_id, f"{body.kql}\n| take 200", body.timespan)
        return {"rows": rows}

    @app.post("/api/v1/ops/{action}", status_code=202)
    def ops(action: str, body: OpIn, ctx: Ctx, p: Writer):
        if action not in SAFE_OPS:
            raise HTTPException(400, f"unknown operation '{action}'")
        if body.app:
            ctx.snapshot().app(body.app)
        if body.env and body.env not in ENVS:
            raise HTTPException(400, "bad env")
        with ctx.sessions() as s:
            op = Operation(action=action, app=body.app, env=body.env, requested_by=p.name)
            s.add(op)
            s.commit()
            return {"operation_id": op.id, "status": "queued"}

    @app.get("/api/v1/heartbeat")
    def heartbeat(ctx: Ctx, authorization: Annotated[str | None, Header()] = None):
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not cfg.heartbeat_token or not hmac.compare_digest(token, cfg.heartbeat_token):
            raise AuthError(401, "invalid_token", "heartbeat token required")
        with ctx.sessions() as s:
            runs = {r.job: r for r in s.scalars(select(WorkerRun))}
        last = max((r.last_finished for r in runs.values() if r.last_finished), default=None)
        stale_min = ctx.snapshot().alert_defaults.get("heartbeat", {}).get("stale_after_minutes", 20)
        ok = bool(last) and (datetime.now(UTC) - _aware(last)).total_seconds() < stale_min * 60
        return {
            "worker_last_run": last.isoformat() if last else None,
            "jobs": {
                j: {"ok": r.ok, "last_finished": r.last_finished.isoformat() if r.last_finished else None}
                for j, r in runs.items()
            },
            "ok": ok and all(r.ok for r in runs.values()),
        }

    return app


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def run() -> None:
    import uvicorn

    from ..telemetry import setup

    setup("platform-api")
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")  # noqa: S104
