import asyncio
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteClient

from blufire_cp.api.main import create_app
from blufire_cp.config import Settings
from blufire_cp.mcp_server import EntraVerifier, PlatformApi, build_server

TENANT = "00000000-0000-0000-0000-0000000000aa"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RESOURCE = "https://mcp.example.com/mcp"
CFG = Settings(
    dev_mode=False, tenant_id=TENANT, mcp_audience="mcp-client-id", mcp_resource_url=RESOURCE, mcp_allowed_oids=("gus",)
)


def tok(**over):
    t = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "tid": TENANT,
        "aud": "mcp-client-id",
        "iat": t,
        "exp": t + 600,
        "oid": "gus",
        "scp": "access_as_user",
        "name": "Gus",
        "azp": "claude",
        **over,
    }
    return jwt.encode(claims, KEY, algorithm="RS256")


def run(coro):
    return asyncio.run(coro)


def test_verifier_rules():
    v = EntraVerifier(CFG, KEY.public_key())
    ok = run(v.verify_token(tok()))
    assert ok and ok.scopes == [f"{RESOURCE}/access_as_user"] and ok.subject == "gus"
    assert run(v.verify_token(tok(oid="stranger"))) is None
    assert run(v.verify_token(tok(scp="other"))) is None
    assert run(v.verify_token(tok(aud="someone-else"))) is None
    assert run(v.verify_token(tok(tid="evil"))) is None


def test_unauthenticated_gets_401_with_resource_metadata():
    server = build_server(CFG, api=PlatformApi(CFG, http=None), key=KEY.public_key())
    app = server.streamable_http_app(stateless_http=True, host="0.0.0.0")
    with StarletteClient(app) as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert r.status_code == 401
        assert "resource_metadata=" in r.headers["www-authenticate"]
        meta = c.get("/.well-known/oauth-protected-resource/mcp").json()
        assert meta["resource"] == RESOURCE
        assert meta["authorization_servers"][0].startswith(f"https://login.microsoftonline.com/{TENANT}/v2.0")


def test_tools_call_api_as_agent(ctx):
    dev = Settings(dev_mode=True)
    api_client = TestClient(create_app(ctx, dev))
    server = build_server(dev, api=PlatformApi(dev, http=api_client))
    names = {t.name for t in run(server.list_tools())}
    assert {"fleet_status", "propose_registry_change", "request_promotion", "run_backup"} <= names
    assert "approve_change" not in names

    def call(name, args):
        result = run(server.call_tool(name, args))
        blocks = result[0] if isinstance(result, tuple) else result
        content = getattr(blocks, "content", blocks)
        return json.loads(content[0].text)

    fleet = call("fleet_status", {})
    assert fleet["prod_total"] == 0
    patch = json.dumps({"alerts": {"latency_p95_ms": 1700}})
    change = call(
        "propose_registry_change",
        {"title": "Tune", "file": "registry/apps/demo-cpa/intake-portal.yaml", "patch_json": patch},
    )
    assert change["status"] == "pending" and change["matched_rules"] == ["actor:agent"]
    nothing = call("request_promotion", {"app_id": "intake-portal", "to_env": "cert"})
    assert nothing["error"] == "nothing_to_promote"
    audit = api_client.get("/api/v1/audit").json()
    assert any("via unknown" in e["actor"] or e["actor_kind"] == "agent" for e in audit)
