"""Azure resource names. Mirrors the Naming table in docs/runtime-config.md and tools/render_params.py
(tools/tests compares them); change all three together."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


def h(*parts: str, n: int = 6) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:n]


@dataclass(frozen=True)
class AppEnvNames:
    subscription: str
    resource_group: str
    shared_resource_group: str
    frontend: str
    backend: str
    identity: str
    postgres_server: str
    database: str
    dbops_job: str
    key_vault: str
    app_insights: str


def app_env(app: dict, env: str, platform: dict, clients: dict[str, dict]) -> AppEnvNames:
    c, a = app["client"], app["id"]
    base = dict(
        frontend=f"ca-{a}-fe-{env}",
        backend=f"ca-{a}-be-{env}",
        identity=f"id-{c}-{a}-{env}",
        app_insights=f"appi-{c}-{a}-{env}",
    )
    if app["stage"] == "incubating":
        sandbox = platform["subscriptions"]["sandbox"]
        return AppEnvNames(
            subscription=sandbox,
            resource_group=f"rg-sandbox-{c}-{a}",
            shared_resource_group="rg-sandbox-shared",
            postgres_server=f"psql-sandbox-{h(sandbox, n=4)}",
            database=f"{c}_{a}_{env}".replace("-", "_"),
            dbops_job="caj-sandbox-dbops",
            key_vault=f"kv-sandbox-{h(sandbox)}",
            **base,
        )
    sub = clients[c]["subscription_id"]
    tier = "prod" if env == "prod" else "nonprod"
    return AppEnvNames(
        subscription=sub,
        resource_group=f"rg-{c}-{a}-{env}",
        shared_resource_group=f"rg-{c}-shared",
        postgres_server=f"psql-{c}-{tier}-{h(sub, n=4)}",
        database=f"{a}_{env}".replace("-", "_"),
        dbops_job=f"caj-{c}-dbops-{tier}",
        key_vault=f"kv-{c}-{tier[0]}-{h(sub, n=4)}",
        **base,
    )
