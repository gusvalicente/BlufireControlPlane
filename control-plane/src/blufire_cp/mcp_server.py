"""MCP server for Claude (or any MCP client). Gus signs in with Entra; tools call platform-api as the Agent role.

The agent role can read everything, run safe operations and propose changes. It can never approve, merge,
delete, rotate secrets or read secret values: platform-api enforces that, not this adapter.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .auth import AuthError, decode
from .config import Settings, settings

Env = Literal["dev", "cert", "prod"]


class EntraVerifier:
    """Accept only Entra tokens issued for this MCP app, to an allowed user, with the access_as_user scope."""

    def __init__(self, cfg: Settings, key=None):
        self.cfg, self.key = cfg, key
        self.scope = f"{cfg.mcp_resource_url}/access_as_user"

    async def verify_token(self, token: str) -> AccessToken | None:
        audiences = [a for a in (self.cfg.mcp_audience, self.cfg.mcp_resource_url) if a]
        try:
            claims = decode(token, audiences, self.cfg, self.key)
        except AuthError:
            return None
        if self.cfg.mcp_allowed_oids and claims.get("oid") not in self.cfg.mcp_allowed_oids:
            return None
        scopes = claims.get("scp", "").split()
        if "access_as_user" not in scopes:
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("azp") or claims.get("appid", ""),
            scopes=[self.scope],
            expires_at=claims.get("exp"),
            resource=self.cfg.mcp_resource_url,
            subject=claims.get("oid"),
            claims={"name": claims.get("name"), "oid": claims.get("oid")},
        )


class PlatformApi:
    """Calls platform-api with the MCP server's own managed identity (Agent app role)."""

    def __init__(self, cfg: Settings, http: httpx.Client | None = None, credential=None):
        self.cfg = cfg
        self.http = http or httpx.Client(base_url=cfg.platform_api_url, timeout=30)
        self._cred = credential
        self._token: tuple[str, float] | None = None

    def _headers(self) -> dict[str, str]:
        user = get_access_token()
        headers = {"X-On-Behalf-Of": (user.claims or {}).get("name", "unknown") if user else "unknown"}
        if self.cfg.dev_mode:
            return {**headers, "X-Dev-Role": "agent"}
        if not self._token or self._token[1] - 120 < time.time():
            if self._cred is None:
                from azure.identity import DefaultAzureCredential

                self._cred = DefaultAzureCredential(managed_identity_client_id=self.cfg.azure_client_id or None)
            t = self._cred.get_token(self.cfg.api_scope)
            self._token = (t.token, t.expires_on)
        return {**headers, "Authorization": f"Bearer {self._token[0]}"}

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> Any:
        r = self.http.request(method, f"/api/v1{path}", json=body, params=params, headers=self._headers())
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            return {"error": err.get("code", r.status_code), "message": err.get("message", r.text)}
        return data


def build_server(cfg: Settings | None = None, api: PlatformApi | None = None, key=None) -> MCPServer:
    cfg = cfg or settings()
    api = api or PlatformApi(cfg)
    verifier = None if cfg.dev_mode else EntraVerifier(cfg, key)
    auth = None
    if verifier:
        auth = AuthSettings(
            issuer_url=f"https://login.microsoftonline.com/{cfg.tenant_id}/v2.0",
            resource_server_url=cfg.mcp_resource_url,
            required_scopes=[verifier.scope],
            validate_token_resource=False,  # Entra v2 tokens carry the app's client id as aud; verified above
        )
    server = MCPServer(
        name="blufire-ops",
        instructions=(
            "BluFire Ops control plane. Read the fleet, incidents, findings, backups and drift. Safe operations "
            "(backup, scan, drift check, restore test, digest) run directly. Any configuration change is proposed "
            "as a change request that Gus approves in the admin UI. You cannot approve changes or see secret values."
        ),
        token_verifier=verifier,
        auth=auth,
    )

    def get(path: str, **params) -> Any:
        return api.call("GET", path, params={k: v for k, v in params.items() if v is not None})

    # ---------------- read
    @server.tool(
        description="Fleet overview: prod health, open P1s, pending approvals, critical findings, drift, cost."
    )
    def fleet_status() -> Any:
        return get("/fleet")

    @server.tool(description="All apps with dev, cert and prod status.")
    def list_apps() -> Any:
        return get("/apps")

    @server.tool(description="One app: registry config, status and which fields need approval.")
    def get_app(app_id: str) -> Any:
        return get(f"/apps/{app_id}")

    @server.tool(
        description="What is running in one environment: release, images, parameters, secret names (never values)."
    )
    def get_runtime(app_id: str, env: Env) -> Any:
        return get(f"/apps/{app_id}/environments/{env}/runtime")

    @server.tool(description="Sentinel, App Insights and heartbeat incidents.")
    def list_incidents(status: Literal["open", "closed", "all"] = "open") -> Any:
        return get("/incidents", status=status)

    @server.tool(
        description="Vulnerability and posture findings from Dependabot, Trivy, Defender and runtime end-of-life."
    )
    def list_findings(status: Literal["open", "resolved", "all"] = "open", severity: str | None = None) -> Any:
        return get("/findings", status=status, severity=severity)

    @server.tool(description="Deployments (Container Apps revisions).")
    def list_deployments(app: str | None = None, env: Env | None = None) -> Any:
        return get("/deployments", app=app, env=env)

    @server.tool(description="Backups by layer (pitr, pre_promotion, nightly, manual, off_cloud).")
    def list_backups(app: str | None = None, env: Env | None = None) -> Any:
        return get("/backups", app=app, env=env)

    @server.tool(description="Restore test history.")
    def list_restore_tests(app: str | None = None) -> Any:
        return get("/restore-tests", app=app)

    @server.tool(description="Differences between git and live Azure.")
    def get_drift(status: Literal["open", "resolved", "all"] = "open") -> Any:
        return get("/drift", status=status)

    @server.tool(description="Change requests and their status.")
    def list_changes(status: Literal["pending", "applied", "rejected", "failed", "all"] = "pending") -> Any:
        return get("/changes", status=status)

    @server.tool(description="Run a read-only KQL query on an allowlisted Log Analytics table. Results are capped.")
    def query_logs(kql: str, timespan: str = "P1D") -> Any:
        return api.call("POST", "/logs/query", {"kql": kql, "timespan": timespan})

    @server.tool(description="Azure cost by client for a month (YYYY-MM, default current).")
    def get_costs(month: str | None = None) -> Any:
        return get("/costs", month=month)

    @server.tool(description="Recent audit log of UI, Claude and CI actions.")
    def get_audit_log(limit: int = 50) -> Any:
        return get("/audit", limit=limit)

    @server.tool(description="Today's digest: P1, P2 and P3 items.")
    def get_digest() -> Any:
        return get("/digest/latest")

    # ---------------- safe operations
    def op(action: str, app: str | None, env: str | None) -> Any:
        return api.call("POST", f"/ops/{action}", {"app": app, "env": env})

    @server.tool(description="Queue an on-demand database dump for one app environment.")
    def run_backup(app: str, env: Env) -> Any:
        return op("backup", app, env)

    @server.tool(description="Queue a restore test of the latest dump into a temporary database.")
    def run_restore_test(app: str, env: Env = "prod") -> Any:
        return op("restore_test", app, env)

    @server.tool(description="Queue a Trivy rescan of every deployed image.")
    def run_scan() -> Any:
        return op("scan", None, None)

    @server.tool(description="Queue a drift check now.")
    def run_drift_check() -> Any:
        return op("drift_check", None, None)

    @server.tool(description="Rebuild and send the digest now.")
    def build_digest() -> Any:
        return op("digest", None, None)

    # ---------------- proposals (always wait for Gus's approval)
    @server.tool(
        description=(
            "Propose a registry change as an RFC 7386 JSON merge patch on one YAML file "
            "(for example registry/apps/<client>/<app>.yaml). Opens a PR that Gus approves in the admin UI."
        )
    )
    def propose_registry_change(title: str, file: str, patch_json: str, reason: str | None = None) -> Any:
        try:
            patch = json.loads(patch_json)
        except json.JSONDecodeError as exc:
            return {"error": "bad_patch", "message": str(exc)}
        return api.call("POST", "/changes", {"title": title, "file": file, "patch": patch, "reason": reason})

    @server.tool(
        description="Propose promoting the images running in the previous environment (dev to cert, cert to prod)."
    )
    def request_promotion(app_id: str, to_env: Literal["cert", "prod"]) -> Any:
        detail = get(f"/apps/{app_id}")
        if "error" in detail:
            return detail
        source = {"cert": "dev", "prod": "cert"}[to_env]
        src = detail["registry"]["environments"][source]
        if not any((src.get("images") or {}).values()):
            return {"error": "nothing_to_promote", "message": f"{source} has no images"}
        patch = {"environments": {to_env: {"images": src["images"], "release": src.get("release")}}}
        return api.call(
            "POST",
            "/changes",
            {
                "title": f"Promote {app_id} {src.get('release') or ''} to {to_env}".strip(),
                "file": detail["path"],
                "patch": patch,
            },
        )

    @server.tool(description="Propose adopting a drift item into git (writes the live value into the registry).")
    def propose_drift_adoption(drift_id: str) -> Any:
        return api.call("POST", f"/drift/{drift_id}/adopt")

    return server


def run() -> None:
    import uvicorn

    from .telemetry import setup

    setup("platform-mcp")
    cfg = settings()
    server = build_server(cfg)
    host = cfg.mcp_resource_url.split("//", 1)[-1].split("/", 1)[0]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=not cfg.dev_mode, allowed_hosts=[host], allowed_origins=["https://claude.ai"]
    )
    app = server.streamable_http_app(transport_security=security, host="0.0.0.0", stateless_http=True)  # noqa: S104
    uvicorn.run(app, host="0.0.0.0", port=8080, proxy_headers=True, forwarded_allow_ips="*")  # noqa: S104
