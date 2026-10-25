"""Compare desired state (registry) with a live Container App definition."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriftItem:
    resource: str
    property: str
    desired: str
    live: str


def _fmt(value) -> str:
    return ", ".join(sorted(value)) if isinstance(value, (set, list, tuple)) else str(value)


def compare(
    resource: str,
    component: str,
    env_cfg: dict,
    live: dict,
    admin_ip: str,
    extra_allowed_cidrs: list[str] | None = None,
) -> list[DriftItem]:
    """`component` is "frontend" or "backend". Only fields the registry owns are compared."""
    items: list[DriftItem] = []
    props = live.get("properties", {})
    template = props.get("template", {})
    scale = template.get("scale", {})
    container = (template.get("containers") or [{}])[0]

    def check(prop: str, desired, actual) -> None:
        if desired != actual:
            items.append(DriftItem(resource, prop, _fmt(desired), _fmt(actual)))

    want = env_cfg.get("scale", {})
    check("scale.minReplicas", want.get("min"), scale.get("minReplicas"))
    check("scale.maxReplicas", want.get("max"), scale.get("maxReplicas"))

    image = (env_cfg.get("images") or {}).get(component)
    if image:
        check("image", image, container.get("image"))

    live_env = {e["name"]: e.get("value") for e in container.get("env", []) if "value" in e}
    for name, value in (env_cfg.get("env_vars") or {}).items():
        check(f"env.{name}", value, live_env.get(name, "(missing)"))

    if component == "frontend":
        origins = env_cfg.get("origins", {})
        rules = (props.get("configuration", {}).get("ingress") or {}).get("ipSecurityRestrictions") or []
        live_cidrs = {r.get("ipAddressRange") for r in rules if r.get("action", "Allow") == "Allow"}
        if origins.get("enabled"):
            desired = {c["cidr"] for c in origins.get("cidrs", [])} | {admin_ip}
            allowed = desired | set(extra_allowed_cidrs or [])
            if not desired <= live_cidrs or not live_cidrs <= allowed:
                check("ingress.ipSecurityRestrictions", desired, live_cidrs)
        elif live_cidrs:
            check("ingress.ipSecurityRestrictions", "(none: origin restriction off)", live_cidrs)
    return items
