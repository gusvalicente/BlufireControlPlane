import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from blufire_cp.api.main import create_app
from blufire_cp.config import Settings
from blufire_cp.models import Drift, Finding, WorkerRun, now

TENANT = "00000000-0000-0000-0000-0000000000aa"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CFG = Settings(
    dev_mode=False,
    tenant_id=TENANT,
    api_audience="api://blufire-platform-api",
    ui_client_id="ui-client",
    heartbeat_token="hb-secret",
)
APP_FILE = "registry/apps/demo-cpa/intake-portal.yaml"


def token(roles, oid="gus-oid", aud="api://blufire-platform-api", **extra):
    t = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "tid": TENANT,
        "aud": aud,
        "iat": t,
        "exp": t + 600,
        "oid": oid,
        "roles": roles,
        "name": "Gus",
        **extra,
    }
    return jwt.encode(claims, KEY, algorithm="RS256")


@pytest.fixture
def client(ctx):
    return TestClient(create_app(ctx, CFG, signing_key=KEY.public_key()))


def h(roles=("Admin",), **kw):
    return {"Authorization": f"Bearer {token(list(roles), **kw)}"}


def test_requires_token(client):
    assert client.get("/api/v1/fleet").status_code == 401
    assert client.get("/api/v1/fleet", headers=h(aud="api://other")).status_code == 401
    assert client.get("/api/v1/fleet", headers=h(roles=())).status_code == 403


def test_fleet_and_apps(client):
    r = client.get("/api/v1/fleet", headers=h())
    assert r.status_code == 200
    body = r.json()
    assert body["prod_total"] == 1 and {a["id"] for a in body["apps"]} == {"intake-portal", "ap-portal"}
    detail = client.get("/api/v1/apps/intake-portal", headers=h()).json()
    assert detail["path"] == APP_FILE and "environments.prod" in detail["approval_fields"]
    assert client.get("/api/v1/apps/nope", headers=h()).status_code == 404


def test_change_flow_with_step_up(client):
    body = {"title": "Prod max 4", "file": APP_FILE, "patch": {"environments": {"prod": {"scale": {"max": 4}}}}}
    c = client.post("/api/v1/changes", json=body, headers=h()).json()
    assert c["status"] == "pending" and c["risk"] == "approval"
    assert client.get("/api/v1/changes", headers=h()).json()[0]["id"] == c["id"]

    no_step = client.post(f"/api/v1/changes/{c['id']}/approve", headers=h())
    assert no_step.status_code == 403 and no_step.json()["error"]["code"] == "step_up_required"

    stale = token([], aud="ui-client", amr=["pwd", "mfa"], auth_time=int(time.time()) - 3600)
    assert (
        client.post(f"/api/v1/changes/{c['id']}/approve", headers={**h(), "X-Step-Up-Token": stale}).status_code == 403
    )

    fresh = token([], aud="ui-client", amr=["pwd", "mfa"], auth_time=int(time.time()) - 30)
    ok = client.post(f"/api/v1/changes/{c['id']}/approve", headers={**h(), "X-Step-Up-Token": fresh})
    assert ok.status_code == 200 and ok.json()["status"] == "applied"


def test_agent_cannot_approve_or_reject(client):
    body = {"title": "Dev max 3", "file": APP_FILE, "patch": {"environments": {"dev": {"scale": {"max": 3}}}}}
    c = client.post("/api/v1/changes", json=body, headers=h(roles=("Agent",))).json()
    assert c["status"] == "pending"
    assert client.post(f"/api/v1/changes/{c['id']}/approve", headers=h(roles=("Agent",))).status_code == 403
    assert (
        client.post(f"/api/v1/changes/{c['id']}/reject", json={"reason": "x"}, headers=h(roles=("Agent",))).status_code
        == 403
    )


def test_invalid_patch_is_422(client):
    body = {"title": "Bad", "file": APP_FILE, "patch": {"environments": {"dev": {"scale": {"min": -1}}}}}
    r = client.post("/api/v1/changes", json=body, headers=h())
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_registry"


def test_ops_and_findings(client, ctx):
    r = client.post("/api/v1/ops/backup", json={"app": "intake-portal", "env": "prod"}, headers=h(roles=("Agent",)))
    assert r.status_code == 202
    assert client.post("/api/v1/ops/delete_everything", json={}, headers=h()).status_code == 400
    with ctx.sessions() as s:
        s.add(
            Finding(
                id="trivy/intake-portal/prod/CVE-1",
                source="trivy",
                app="intake-portal",
                env="prod",
                title="openssl",
                severity="critical",
            )
        )
        s.commit()
    assert client.get("/api/v1/fleet", headers=h()).json()["critical_findings"] == 1
    a = client.post(
        "/api/v1/findings/trivy/intake-portal/prod/CVE-1/ack", json={"note": "base image bump queued"}, headers=h()
    )
    assert a.status_code == 200 and a.json()["status"] == "acknowledged"


def test_prod_drift_revert_needs_admin(client, ctx):
    with ctx.sessions() as s:
        s.add(
            Drift(
                id="ca-intake-portal-be-prod|scale.maxReplicas",
                app="intake-portal",
                env="prod",
                resource="ca-intake-portal-be-prod",
                property="scale.maxReplicas",
                desired="3",
                live="10",
            )
        )
        s.commit()
    did = "ca-intake-portal-be-prod|scale.maxReplicas"
    assert client.post(f"/api/v1/drift/{did}/revert", headers=h(roles=("Agent",))).status_code == 403
    assert client.post(f"/api/v1/drift/{did}/revert", headers=h()).status_code == 202
    adopt = client.post(f"/api/v1/drift/{did}/adopt", headers=h()).json()
    assert adopt["risk"] == "approval" and "max: 10" in adopt["diff"]


def test_heartbeat(client, ctx):
    assert client.get("/api/v1/heartbeat").status_code == 401
    with ctx.sessions() as s:
        s.add(WorkerRun(job="sync", last_finished=now(), ok=True))
        s.commit()
    r = client.get("/api/v1/heartbeat", headers={"Authorization": "Bearer hb-secret"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_audit_records_calls(client):
    client.get("/api/v1/fleet", headers=h())
    client.get("/api/v1/fleet", headers=h(roles=()))
    events = client.get("/api/v1/audit", headers=h()).json()
    assert {e["result"] for e in events} >= {"ok", "denied"}


def test_probes(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/readyz").json() == {"ok": True}
