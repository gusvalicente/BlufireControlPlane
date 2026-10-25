"""Daily digest: P1s from the last 24 hours, then P2s, then a P3 summary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Backup, Change, Cost, Deployment, Drift, Finding, Incident, RestoreTest
from .registry import Snapshot


def build(snap: Snapshot, s: Session, at: datetime | None = None) -> dict:
    at = at or datetime.now(UTC)
    since = at - timedelta(hours=24)
    p1, p2, p3 = [], [], []

    for i in s.scalars(select(Incident).where(Incident.opened_at >= since)):
        bucket = p1 if i.severity == "p1" else p2 if i.severity == "p2" else p3
        bucket.append({"title": i.title, "detail": f"{i.source}, {i.status}", "link": i.link})
    for b in s.scalars(select(Backup).where(Backup.created_at >= since, Backup.result != "ok")):
        p1.append({"title": f"Backup {b.result}: {b.app} {b.env} ({b.layer})", "detail": b.location, "link": None})
    for r in s.scalars(select(RestoreTest).where(RestoreTest.started_at >= since, RestoreTest.result == "failed")):
        p1.append({"title": f"Restore test failed: {r.app}", "detail": ", ".join(r.checks), "link": None})
    for d in s.scalars(select(Deployment).where(Deployment.started_at >= since, Deployment.result == "rolled_back")):
        p1.append({"title": f"Rolled back: {d.app} {d.env}", "detail": d.image_digest, "link": None})

    prod_apps = {a for a, doc in snap.apps.items() if doc["stage"] == "graduated"}
    for f in s.scalars(select(Finding).where(Finding.status == "open", Finding.severity.in_(["critical", "high"]))):
        bucket = p2 if f.app in prod_apps and f.env in (None, "prod") else p3
        due = f" due {f.due_at:%b %d}" if f.due_at else ""
        bucket.append(
            {"title": f"{f.severity.title()}: {f.title}", "detail": f"{f.app or 'platform'}{due}", "link": f.link}
        )
    for d in s.scalars(select(Drift).where(Drift.status == "open")):
        (p2 if d.env == "prod" else p3).append(
            {"title": f"Drift: {d.app} {d.env} {d.property}", "detail": f"git {d.desired}, live {d.live}", "link": None}
        )
    today = at.date()
    for app_id, app in snap.apps.items():
        for runtime, eol in (app.get("stack", {}).get("runtime_eol") or {}).items():
            days = (datetime.fromisoformat(eol).date() - today).days
            if days <= 90:
                p2.append({"title": f"{runtime} end of life in {days} days", "detail": app_id, "link": None})

    pending = s.scalars(select(Change).where(Change.status == "pending")).all()
    if pending:
        p3.append(
            {
                "title": f"{len(pending)} change(s) waiting for approval",
                "detail": ", ".join(c.title for c in pending),
                "link": None,
            }
        )
    ok_backups = s.scalars(select(Backup).where(Backup.created_at >= since, Backup.result == "ok")).all()
    p3.append({"title": f"{len(ok_backups)} backups succeeded", "detail": "", "link": None})
    month = at.strftime("%Y-%m")
    costs = s.scalars(select(Cost).where(Cost.month == month)).all()
    if costs:
        total = sum(c.usd for c in costs)
        p3.append(
            {
                "title": f"Azure month to date ${total:,.2f}",
                "detail": ", ".join(f"{c.client} ${c.usd:,.2f}" for c in costs),
                "link": None,
            }
        )

    return {"generated_at": at.isoformat(), "p1": p1, "p2": p2, "p3": p3, "text": render_text(p1, p2, p3, at)}


def render_text(p1: list, p2: list, p3: list, at: datetime) -> str:
    lines = [f"BluFire Ops digest, {at:%a %b %d %Y}", ""]
    for label, items in (("P1, last 24 hours", p1), ("P2, needs attention", p2), ("P3, summary", p3)):
        lines.append(f"{label}: {len(items) or 'none'}")
        lines.extend(f"  - {i['title']}" + (f" ({i['detail']})" if i["detail"] else "") for i in items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
