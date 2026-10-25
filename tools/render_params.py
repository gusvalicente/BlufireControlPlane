#!/usr/bin/env python3
"""Render Bicep deployment parameters from the registry.

Reads platform.yaml, registry/clients/*.yaml, registry/apps/<client>/<app>.yaml, alerts/defaults.yaml,
infra/platform-settings.json and infra/platform-images.json. Validates everything, then writes one ARM parameter file
per deployment plus manifest.json (deployment order) into the output directory.

    python tools/render_params.py --out build/params      # validate and render
    python tools/render_params.py --check                 # validate only
    python tools/render_params.py --names                 # print platform-level resource names as JSON

Resource names follow the Naming table in docs/runtime-config.md and control-plane/src/blufire_cp/naming.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import jsonschema
import yaml

ENVS = ("dev", "cert", "prod")
PARAMS_SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
NAME_LIMITS = {"container_app": 32, "job": 32, "key_vault": 24, "postgres": 63, "storage": 24}


@dataclass
class Registry:
    platform: dict
    clients: dict[str, dict]
    apps: list[tuple[str, dict]]  # (repo-relative path, document)
    alerts: dict
    settings: dict
    images: dict


@dataclass
class Result:
    files: dict[str, dict] = field(default_factory=dict)
    manifest: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load(root: Path) -> Registry:
    clients = {}
    for p in sorted((root / "registry/clients").glob("*.yaml")):
        doc = _yaml(p)
        clients[doc.get("id", p.stem)] = doc
    apps = [
        (str(p.relative_to(root)), _yaml(p))
        for p in sorted((root / "registry/apps").glob("*/*.yaml"))
    ]
    return Registry(
        platform=_yaml(root / "platform.yaml"),
        clients=clients,
        apps=apps,
        alerts=_yaml(root / "alerts/defaults.yaml"),
        settings=_json(root / "infra/platform-settings.json", {}),
        images=_json(root / "infra/platform-images.json", {}),
    )


def h(*parts: str, n: int = 6) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:n]


def unset(value) -> bool:
    return value is None or (isinstance(value, str) and ("REPLACE" in value or value == ""))


def clean(value) -> str:
    return "" if unset(value) else str(value)


def platform_names(platform: dict) -> dict:
    psub = platform["subscriptions"]["platform"]
    return {
        "resourceGroup": "rg-platform-prod",
        "identity": "id-platform-prod",
        "dbopsIdentity": "id-platform-dbops",
        "dbopsJob": "caj-platform-dbops",
        "logAnalytics": "log-platform-prod",
        "appInsights": "appi-platform-prod",
        "acr": f"acrblufire{h(psub)}",
        "keyVault": f"kv-blufire-{h(psub)}",
        "actionGroup": "ag-platform-p1",
        "vnet": "vnet-platform-prod",
        "cae": "cae-platform-prod",
        "stateDb": f"psql-platform-{h(psub, n=4)}",
        "emailService": f"ecs-blufire-{h(psub)}",
        "communicationService": f"acs-blufire-{h(psub)}",
        "apiApp": "ca-platform-api-prod",
        "uiApp": "ca-platform-ui-prod",
        "mcpApp": "ca-platform-mcp-prod",
        "backupResourceGroup": "rg-backup-prod",
        "backupStorage": f"stblufirebkp{h(platform['subscriptions']['backup'])}",
    }


def sandbox_names(platform: dict) -> dict:
    return {
        "resourceGroup": "rg-sandbox-shared",
        "vnet": "vnet-sandbox",
        "cae": "cae-sandbox",
        "postgres": f"psql-sandbox-{h(platform['subscriptions']['sandbox'], n=4)}",
        "keyVault": f"kv-sandbox-{h(platform['subscriptions']['sandbox'])}",
        "dbopsJob": "caj-sandbox-dbops",
        "dbopsIdentity": "id-sandbox-dbops",
    }


def client_names(c: str, subscription_id: str) -> dict:
    """Postgres and Key Vault names are global in Azure, so they carry a short hash of the client subscription."""
    sfx = h(subscription_id, n=4)
    return {
        "resourceGroup": f"rg-{c}-shared",
        "vnet": f"vnet-{c}",
        "cae": {"prod": f"cae-{c}-prod", "nonprod": f"cae-{c}-nonprod"},
        "postgres": {"prod": f"psql-{c}-prod-{sfx}", "nonprod": f"psql-{c}-nonprod-{sfx}"},
        "keyVault": {"prod": f"kv-{c}-p-{sfx}", "nonprod": f"kv-{c}-n-{sfx}"},
        "dbopsJob": {"prod": f"caj-{c}-dbops-prod", "nonprod": f"caj-{c}-dbops-nonprod"},
        "dbopsIdentity": f"id-{c}-dbops",
    }


def app_env_names(app: dict, env: str, platform: dict, clients: dict[str, dict]) -> dict:
    """Same rules as blufire_cp.naming.app_env (tests compare the two)."""
    c, a = app["client"], app["id"]
    base = {
        "frontend": f"ca-{a}-fe-{env}",
        "backend": f"ca-{a}-be-{env}",
        "identity": f"id-{c}-{a}-{env}",
        "app_insights": f"appi-{c}-{a}-{env}",
    }
    if app["stage"] == "incubating":
        sb = sandbox_names(platform)
        return base | {
            "subscription": platform["subscriptions"]["sandbox"],
            "resource_group": f"rg-sandbox-{c}-{a}",
            "shared_resource_group": sb["resourceGroup"],
            "cae": sb["cae"],
            "postgres_server": sb["postgres"],
            "database": f"{c}_{a}_{env}".replace("-", "_"),
            "dbops_job": sb["dbopsJob"],
            "key_vault": sb["keyVault"],
        }
    tier = "prod" if env == "prod" else "nonprod"
    cn = client_names(c, clients[c]["subscription_id"])
    return base | {
        "subscription": clients[c]["subscription_id"],
        "resource_group": f"rg-{c}-{a}-{env}",
        "shared_resource_group": cn["resourceGroup"],
        "cae": cn["cae"][tier],
        "postgres_server": cn["postgres"][tier],
        "database": f"{a}_{env}".replace("-", "_"),
        "dbops_job": cn["dbopsJob"][tier],
        "key_vault": cn["keyVault"][tier],
    }


def _check_len(kind: str, name: str, res: Result) -> None:
    limit = NAME_LIMITS[kind]
    if len(name) > limit:
        res.errors.append(
            f"name '{name}' is {len(name)} characters; Azure allows {limit} for {kind.replace('_', ' ')}. "
            "Shorten the client or app id."
        )


def _params(values: dict) -> dict:
    return {
        "$schema": PARAMS_SCHEMA,
        "contentVersion": "1.0.0.0",
        "parameters": {k: {"value": v} for k, v in values.items()},
    }


def _schemas(root: Path) -> tuple[dict, dict]:
    def load_schema(name: str) -> dict:
        return json.loads((root / "registry/schema" / name).read_text())

    return load_schema("client.schema.json"), load_schema("app.schema.json")


def validate(reg: Registry, root: Path, res: Result) -> None:
    client_schema, app_schema = _schemas(root)
    fmt = jsonschema.FormatChecker()
    for cid, doc in reg.clients.items():
        for e in jsonschema.Draft202012Validator(client_schema, format_checker=fmt).iter_errors(doc):
            res.errors.append(f"registry/clients/{cid}.yaml: {'.'.join(map(str, e.path)) or '<root>'}: {e.message}")
        pg = doc.get("postgres") or {}
        if pg.get("prod_high_availability") and str(pg.get("prod_sku", "Standard_B")).startswith("Standard_B"):
            res.errors.append(f"registry/clients/{cid}.yaml: prod_high_availability needs a General Purpose prod_sku")

    seen = set()
    for path, app in reg.apps:
        errs = list(jsonschema.Draft202012Validator(app_schema, format_checker=fmt).iter_errors(app))
        for e in errs:
            res.errors.append(f"{path}: {'.'.join(map(str, e.path)) or '<root>'}: {e.message}")
        if errs:
            continue
        key = (app["client"], app["id"])
        if key in seen:
            res.errors.append(f"{path}: duplicate app {key[0]}/{key[1]}")
        seen.add(key)
        expected = f"registry/apps/{app['client']}/{app['id']}.yaml"
        if path != expected:
            res.errors.append(f"{path}: file must be at {expected}")
        client = reg.clients.get(app["client"])
        if client is None:
            res.errors.append(f"{path}: client '{app['client']}' has no file in registry/clients")
            continue
        if app["stage"] == "graduated" and not client.get("subscription_id"):
            res.errors.append(f"{path}: graduated app needs subscription_id on client '{app['client']}'")
        if app["stage"] == "incubating" and app["client_data"]:
            res.warnings.append(f"{path}: client_data is true while incubating; the sandbox server is shared")
        for env in ENVS:
            e = app["environments"][env]
            if e["origins"]["enabled"] and not e["origins"]["cidrs"]:
                res.errors.append(f"{path}: environments.{env}.origins is enabled with no cidrs")
            if e["scale"]["min"] > e["scale"]["max"]:
                res.errors.append(f"{path}: environments.{env}.scale.min is greater than max")
            images = e.get("images") or {}
            if (images.get("frontend") is None) != (images.get("backend") is None):
                res.errors.append(f"{path}: environments.{env}.images needs both frontend and backend, or neither")


def _digest_cron(platform: dict) -> str:
    digest = platform.get("digest") or {}
    hh, mm = map(int, str(digest.get("send_local_time", "07:00")).split(":"))
    tz = ZoneInfo(digest.get("timezone", "America/New_York"))
    local = dt.datetime.combine(dt.datetime.now(tz).date(), dt.time(hh, mm), tzinfo=tz)
    utc = local.astimezone(dt.UTC)
    return f"{utc.minute} {utc.hour} * * *"


def _rule_name(label: str, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9-]+", "-", label).strip("-").lower()[:40] or "cidr"
    name, i = base, 2
    while name in used:
        name, i = f"{base}-{i}", i + 1
    used.add(name)
    return name


def _deployment_name(*parts: str) -> str:
    name = "bf-" + "-".join(parts)
    return name if len(name) <= 64 else f"{name[:55]}-{h(name, n=8)}"


def render(reg: Registry, root: Path) -> Result:
    res = Result()
    validate(reg, root, res)
    if res.errors:
        return res

    p = reg.platform
    subs = p["subscriptions"]
    location = p["region"]
    pn = platform_names(p)
    settings = {
        "apiAudience": "api://blufire-platform-api",
        "uiClientId": "",
        "mcpClientId": "",
        "adminObjectId": "",
        "githubAppId": "",
        "githubAppInstallationId": "",
        "ciPrincipalIds": [],
        "platformPrincipalId": "",
        "macMiniPrincipalId": "",
        "stepUpAcrs": "",
        "availabilityTestCidrs": [],
    } | reg.settings
    platform_principal = settings["platformPrincipalId"]
    workspace_id = (
        f"/subscriptions/{subs['platform']}/resourceGroups/{pn['resourceGroup']}"
        f"/providers/Microsoft.OperationalInsights/workspaces/{pn['logAnalytics']}"
    )
    action_group_id = (
        f"/subscriptions/{subs['platform']}/resourceGroups/{pn['resourceGroup']}"
        f"/providers/Microsoft.Insights/actionGroups/{pn['actionGroup']}"
    )
    acr_login = f"{pn['acr']}.azurecr.io"
    network = p.get("network") or {}
    admin_cidr = network.get("admin_static_ip", "")
    domains = p.get("domains") or {}
    alerts = p.get("alerts") or {}
    pgcfg = p.get("postgres") or {}
    images = reg.images
    shared = {
        "platformSubscriptionId": subs["platform"],
        "platformResourceGroupName": pn["resourceGroup"],
        "acrName": pn["acr"],
        "acrLoginServer": acr_login,
        "dbopsImage": clean(images.get("dbops")),
        "backupSubscriptionId": subs["backup"],
        "backupResourceGroupName": pn["backupResourceGroup"],
        "backupStorageAccountName": pn["backupStorage"],
        "platformPrincipalId": platform_principal,
    }

    for key, value in [("tenant_id", p.get("tenant_id")), ("admin_static_ip", admin_cidr),
                       ("domains.admin_ui", domains.get("admin_ui")), ("domains.mcp", domains.get("mcp")),
                       ("alerts.email", alerts.get("email"))]:
        if unset(value):
            res.warnings.append(f"platform.yaml: {key} is not set")
    if not platform_principal:
        res.warnings.append("infra/platform-settings.json: platformPrincipalId is empty (set by bootstrap/60)")

    def add(kind: str, name: str, subscription: str, template: str, fname: str, values: dict, meta: dict) -> None:
        res.files[fname] = _params(values)
        res.manifest.append({
            "name": name, "kind": kind, "subscription": subscription, "location": location,
            "template": template, "parameters": fname, "meta": meta,
        })

    add("platform", _deployment_name("platform"), subs["platform"], "infra/stacks/platform.bicep", "platform.json", {
        "location": location,
        "tenantId": p["tenant_id"],
        "resourceGroupName": pn["resourceGroup"],
        "names": pn,
        "adminStaticIp": admin_cidr,
        "mcpClientCidrs": network.get("mcp_client_cidrs") or [],
        "uiDomain": clean(domains.get("admin_ui")),
        "mcpDomain": clean(domains.get("mcp")),
        "bindCustomDomains": True,
        "alertEmail": clean(alerts.get("email")),
        "smsCountryCode": str(alerts.get("sms_country_code", "1")),
        "smsNumber": "" if set(str(alerts.get("sms_number", ""))) <= {"0"} else str(alerts.get("sms_number")),
        "pushEmail": clean(alerts.get("azure_app_push_email")),
        "pgAdminGroupObjectId": pgcfg["entra_admin_group_object_id"],
        "backupSubscriptionId": subs["backup"],
        "backupResourceGroupName": pn["backupResourceGroup"],
        "backupStorageAccountName": pn["backupStorage"],
        "githubOwner": p["github"]["org"],
        "githubRepo": p["github"]["platform_repo"],
        "settings": settings,
        "controlPlaneImage": clean(images.get("controlPlane")),
        "uiImage": clean(images.get("ui")),
        "dbopsImage": clean(images.get("dbops")),
        "deployApps": bool(clean(images.get("controlPlane")) and clean(images.get("ui"))),
        "digestCronUtc": _digest_cron(p),
    }, {})

    sn = sandbox_names(p)
    _check_len("key_vault", sn["keyVault"], res)
    add("sandbox", _deployment_name("sandbox"), subs["sandbox"], "infra/stacks/sandbox.bicep", "sandbox.json", {
        "location": location,
        "tenantId": p["tenant_id"],
        "names": sn,
        "pgSku": pgcfg.get("sandbox_sku", "Standard_B2s"),
        "pgStorageGB": int(pgcfg.get("storage_gb", 32)),
        "pgAdminGroupObjectId": pgcfg["entra_admin_group_object_id"],
        "workspaceId": workspace_id,
        **shared,
    }, {})

    subnet_ids = [
        (f"/subscriptions/{subs['platform']}/resourceGroups/{pn['resourceGroup']}"
         f"/providers/Microsoft.Network/virtualNetworks/{pn['vnet']}/subnets/snet-cae"),
        (f"/subscriptions/{subs['sandbox']}/resourceGroups/{sn['resourceGroup']}"
         f"/providers/Microsoft.Network/virtualNetworks/{sn['vnet']}/subnets/snet-cae"),
    ]

    graduated_clients = sorted({a["client"] for _, a in reg.apps if a["stage"] == "graduated"})
    for cid in graduated_clients:
        client = reg.clients[cid]
        cn = client_names(cid, client["subscription_id"])
        for kind, names in (("key_vault", cn["keyVault"]), ("job", cn["dbopsJob"]), ("postgres", cn["postgres"])):
            for n in names.values():
                _check_len(kind, n, res)
        pg = client.get("postgres") or {}
        retention = max(
            [(a.get("backup") or {}).get("pitr_retention_days", 35)
             for _, a in reg.apps if a["client"] == cid and a["stage"] == "graduated"] or [35]
        )
        add("client", _deployment_name("client", cid), client["subscription_id"], "infra/stacks/client.bicep",
            f"client-{cid}.json", {
                "location": location,
                "tenantId": p["tenant_id"],
                "clientId": cid,
                "names": cn,
                "prodSku": pg.get("prod_sku", pgcfg.get("default_prod_sku", "Standard_B2s")),
                "nonprodSku": pg.get("nonprod_sku", pgcfg.get("default_nonprod_sku", "Standard_B1ms")),
                "prodHighAvailability": bool(pg.get("prod_high_availability", False)),
                "prodRetentionDays": int(retention),
                "pgStorageGB": int(pgcfg.get("storage_gb", 32)),
                "pgAdminGroupObjectId": pgcfg["entra_admin_group_object_id"],
                "workspaceId": workspace_id,
                **{k: v for k, v in shared.items()},
            }, {"client": cid})
        for tier in ("prod", "nonprod"):
            subnet_ids.append(
                f"/subscriptions/{client['subscription_id']}/resourceGroups/{cn['resourceGroup']}"
                f"/providers/Microsoft.Network/virtualNetworks/{cn['vnet']}/subnets/snet-cae-{tier}"
            )

    avail = reg.alerts.get("availability_test") or {}
    avail_cidrs = settings.get("availabilityTestCidrs") or []
    for path, app in reg.apps:
        for env in ENVS:
            e = app["environments"][env]
            n = app_env_names(app, env, p, reg.clients)
            for key in ("frontend", "backend"):
                _check_len("container_app", n[key], res)
            images_env = e.get("images") or {}
            if images_env.get("frontend") is None:
                continue  # not deployed yet; the first dev image bump creates it
            used: set[str] = set()
            allowed = []
            if e["origins"]["enabled"]:
                allowed = [{"name": _rule_name(c["label"], used), "cidr": c["cidr"]} for c in e["origins"]["cidrs"]]
                allowed.append({"name": _rule_name("blufire-admin", used), "cidr": admin_cidr})
                allowed += [{"name": _rule_name(f"availability-{i}", used), "cidr": c} for i, c in enumerate(avail_cidrs)]
            test_on = env == "prod" and app["stage"] == "graduated"
            if test_on and e["origins"]["enabled"] and not avail_cidrs:
                res.warnings.append(
                    f"{path}: prod origins are on but availabilityTestCidrs is empty; the availability test will fail"
                )
            values = {
                "location": location,
                "clientId": app["client"],
                "appId": app["id"],
                "env": env,
                "resourceGroupName": n["resource_group"],
                "sharedResourceGroupName": n["shared_resource_group"],
                "caeName": n["cae"],
                "postgresServerName": n["postgres_server"],
                "databaseName": n["database"],
                "keyVaultName": n["key_vault"],
                "identityName": n["identity"],
                "appInsightsName": n["app_insights"],
                "frontendName": n["frontend"],
                "backendName": n["backend"],
                "frontendImage": images_env["frontend"],
                "backendImage": images_env["backend"],
                "minReplicas": e["scale"]["min"],
                "maxReplicas": e["scale"]["max"],
                "allowedCidrs": allowed,
                "envVars": e.get("env_vars") or {},
                "secretNames": e.get("secrets") or [],
                "entraClientId": app["auth"].get("entra_app_id") or "",
                "allowedTenants": app["auth"]["allowed_tenants"],
                "workspaceId": workspace_id,
                "actionGroupId": action_group_id,
                "availabilityTest": test_on,
                "availabilityFrequencySeconds": int(avail.get("frequency_seconds", 900)),
                "availabilityLocations": int(avail.get("locations", 5)),
                "platformSubscriptionId": subs["platform"],
                "platformResourceGroupName": pn["resourceGroup"],
                "acrName": pn["acr"],
                "acrLoginServer": acr_login,
                "platformPrincipalId": platform_principal,
            }
            add("app", _deployment_name("app", app["client"], app["id"], env), n["subscription"],
                "infra/stacks/app.bicep", f"app-{app['client']}-{app['id']}-{env}.json", values, {
                    "client": app["client"], "app": app["id"], "env": env, "stage": app["stage"],
                    "resource_group": n["resource_group"], "shared_resource_group": n["shared_resource_group"],
                    "frontend": n["frontend"], "backend": n["backend"], "database": n["database"],
                    "dbops_job": n["dbops_job"], "release": e.get("release"), "identity": n["identity"],
                })

    admin_ip = admin_cidr.removesuffix("/32")
    add("backup", _deployment_name("backup"), subs["backup"], "infra/stacks/backup.bicep", "backup.json", {
        "location": location,
        "resourceGroupName": pn["backupResourceGroup"],
        "storageAccountName": pn["backupStorage"],
        "workspaceId": workspace_id,
        "adminIp": admin_ip,
        "allowedSubnetIds": subnet_ids,
        "macMiniPrincipalId": settings.get("macMiniPrincipalId", ""),
    }, {})
    return res


def write(res: Result, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    for name, data in res.files.items():
        (out / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (out / "manifest.json").write_text(json.dumps(res.manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--out", type=Path, default=Path("build/params"))
    ap.add_argument("--check", action="store_true", help="validate only")
    ap.add_argument("--names", action="store_true", help="print platform resource names as JSON")
    args = ap.parse_args(argv)

    reg = load(args.root)
    if args.names:
        print(json.dumps(platform_names(reg.platform) | {"sandbox": sandbox_names(reg.platform)}, indent=2))
        return 0
    res = render(reg, args.root)
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if res.errors:
        for e in res.errors:
            print(f"error: {e}", file=sys.stderr)
        return 1
    if not args.check:
        write(res, args.out)
        print(f"rendered {len(res.manifest)} deployments to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
