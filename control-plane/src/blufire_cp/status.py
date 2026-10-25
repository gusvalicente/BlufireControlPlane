"""Read models for the UI and MCP: app summaries, fleet view, digest."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Change, Cost, Drift, EnvStatus, Finding, Incident
from .registry import ENVS, Snapshot

UP = {"healthy", "degraded"}


def app_summary(snap: Snapshot, s: Session, app_id: str) -> dict:
    app = snap.app(app_id)
    rows = {r.env: r for r in s.scalars(select(EnvStatus).where(EnvStatus.app == app_id))}
    envs = []
    for env in ENVS:
        r = rows.get(env)
        not_deployed = not any((app["environments"][env].get("images") or {}).values())
        envs.append(
            {
                "env": env,
                "health": r.health if r else ("not_deployed" if not_deployed else "unknown"),
                "summary": r.summary if r else ("Not deployed" if not_deployed else "No data yet"),
                "release": (r.release if r else None) or app["environments"][env].get("release"),
                "p95_ms": r.p95_ms if r else None,
                "error_rate_pct": r.error_rate_pct if r else None,
                "replicas": {"current": r.replicas_current, "max": r.replicas_max}
                if r and r.replicas_max is not None
                else None,
            }
        )
    badges = []
    critical = s.scalar(
        select(func.count())
        .select_from(Finding)
        .where(Finding.app == app_id, Finding.status == "open", Finding.severity == "critical")
    )
    if critical:
        badges.append({"kind": "critical_finding", "count": critical})
    path = snap.app_files[app_id]
    pending = s.scalar(select(func.count()).select_from(Change).where(Change.file == path, Change.status == "pending"))
    if pending:
        badges.append({"kind": "approval", "count": pending})
    drift = s.scalar(select(func.count()).select_from(Drift).where(Drift.app == app_id, Drift.status == "open"))
    if drift:
        badges.append({"kind": "drift", "count": drift})
    if app["stage"] == "incubating" and app["client_data"]:
        badges.append({"kind": "client_data_in_sandbox", "count": 1})
    return {
        "id": app_id,
        "client": app["client"],
        "client_name": snap.clients.get(app["client"], {}).get("name", app["client"]),
        "name": app["name"],
        "stage": app["stage"],
        "client_data": app["client_data"],
        "envs": envs,
        "badges": badges,
    }


def fleet(snap: Snapshot, s: Session) -> dict:
    apps = [app_summary(snap, s, a) for a in sorted(snap.apps)]
    live = [a for a in apps if a["stage"] == "graduated" and a["envs"][2]["health"] != "not_deployed"]
    prod_up = sum(1 for a in live if a["envs"][2]["health"] in UP)
    open_p1 = s.scalar(
        select(func.count()).select_from(Incident).where(Incident.status == "open", Incident.severity == "p1")
    )
    pending = s.scalar(select(func.count()).select_from(Change).where(Change.status == "pending"))
    critical = s.scalar(
        select(func.count()).select_from(Finding).where(Finding.status == "open", Finding.severity == "critical")
    )
    drift = s.scalar(select(func.count()).select_from(Drift).where(Drift.status == "open"))
    month = datetime.now(UTC).strftime("%Y-%m")
    cost = s.scalar(select(func.coalesce(func.sum(Cost.usd), 0.0)).where(Cost.month == month)) or 0.0

    if open_p1:
        headline = f"{open_p1} open P1 incident{'s' if open_p1 != 1 else ''}"
    elif live and prod_up == len(live):
        headline = f"All {len(live)} prod app{'s are' if len(live) != 1 else ' is'} up"
    elif live:
        headline = f"{len(live) - prod_up} of {len(live)} prod apps need attention"
    else:
        headline = "No prod apps deployed yet"
    detail_parts = []
    if pending:
        detail_parts.append(f"{pending} change{'s wait' if pending != 1 else ' waits'} for your approval.")
    if critical:
        detail_parts.append(f"{critical} critical finding{'s' if critical != 1 else ''} open.")
    return {
        "headline": headline,
        "detail": " ".join(detail_parts) or "Nothing needs you right now.",
        "prod_up": prod_up,
        "prod_total": len(live),
        "open_p1": open_p1,
        "pending_approvals": pending,
        "critical_findings": critical,
        "drift_open": drift,
        "cost_mtd_usd": round(float(cost), 2),
        "apps": apps,
    }
