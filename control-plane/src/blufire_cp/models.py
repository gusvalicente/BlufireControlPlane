"""State database tables (observed state). Desired state lives in git, never here."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), dict: JSON, list: JSON}


class Change(Base):
    __tablename__ = "changes"
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    file: Mapped[str] = mapped_column(String(300))
    operation: Mapped[str] = mapped_column(String(10), default="update")  # create | update | delete
    actor_kind: Mapped[str] = mapped_column(String(10))
    actor_oid: Mapped[str] = mapped_column(String(64))
    actor_name: Mapped[str] = mapped_column(String(200))
    risk: Mapped[str] = mapped_column(String(10))
    matched_rules: Mapped[list] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(10))  # applied | pending | rejected | failed
    diff: Mapped[str] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(String(100))
    files: Mapped[list] = mapped_column(default=list)  # files the PR may touch
    head_sha: Mapped[str | None] = mapped_column(String(64))  # the commit Gus reviews; merge refuses anything else
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None]
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)


class EnvStatus(Base):
    __tablename__ = "env_status"
    app: Mapped[str] = mapped_column(String(40), primary_key=True)
    env: Mapped[str] = mapped_column(String(5), primary_key=True)
    health: Mapped[str] = mapped_column(String(20), default="unknown")
    summary: Mapped[str] = mapped_column(String(100), default="No data yet")
    release: Mapped[str | None] = mapped_column(String(60))
    p95_ms: Mapped[float | None] = mapped_column(Float)
    error_rate_pct: Mapped[float | None] = mapped_column(Float)
    replicas_current: Mapped[int | None] = mapped_column(Integer)
    replicas_max: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(default=now)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Container Apps revision name
    app: Mapped[str] = mapped_column(String(40), index=True)
    env: Mapped[str] = mapped_column(String(5))
    component: Mapped[str] = mapped_column(String(10))  # frontend | backend
    release: Mapped[str | None] = mapped_column(String(60))
    image_digest: Mapped[str] = mapped_column(String(300))
    git_sha: Mapped[str | None] = mapped_column(String(64))
    approver: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]
    result: Mapped[str] = mapped_column(String(15), default="running")


class Backup(Base):
    __tablename__ = "backups"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)  # blob path of the result file
    app: Mapped[str] = mapped_column(String(40), index=True)
    env: Mapped[str] = mapped_column(String(5))
    layer: Mapped[str] = mapped_column(String(15))
    location: Mapped[str] = mapped_column(String(400))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=now)
    result: Mapped[str] = mapped_column(String(10))


class RestoreTest(Base):
    __tablename__ = "restore_tests"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    app: Mapped[str] = mapped_column(String(40), index=True)
    backup_id: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(default=now)
    duration_s: Mapped[float | None] = mapped_column(Float)
    checks: Mapped[list] = mapped_column(default=list)
    result: Mapped[str] = mapped_column(String(10))


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)  # stable key from the source
    source: Mapped[str] = mapped_column(String(15))
    app: Mapped[str | None] = mapped_column(String(40), index=True)
    env: Mapped[str | None] = mapped_column(String(5))
    title: Mapped[str] = mapped_column(String(300))
    package: Mapped[str | None] = mapped_column(String(200))
    cve: Mapped[str | None] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(15), default="open")
    first_seen: Mapped[datetime] = mapped_column(default=now)
    last_seen: Mapped[datetime] = mapped_column(default=now)
    due_at: Mapped[datetime | None]
    link: Mapped[str | None] = mapped_column(String(400))
    note: Mapped[str | None] = mapped_column(Text)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source: Mapped[str] = mapped_column(String(15))
    severity: Mapped[str] = mapped_column(String(3))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10))
    opened_at: Mapped[datetime] = mapped_column(default=now)
    closed_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(400))


class Drift(Base):
    __tablename__ = "drift"
    id: Mapped[str] = mapped_column(String(300), primary_key=True)  # resource|property
    app: Mapped[str] = mapped_column(String(40), index=True)
    env: Mapped[str] = mapped_column(String(5))
    resource: Mapped[str] = mapped_column(String(200))
    property: Mapped[str] = mapped_column(String(100))
    desired: Mapped[str] = mapped_column(Text)
    live: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[str | None] = mapped_column(String(200))
    detected_at: Mapped[datetime] = mapped_column(default=now)
    status: Mapped[str] = mapped_column(String(10), default="open")


class SecretMeta(Base):
    __tablename__ = "secrets_meta"
    id: Mapped[str] = mapped_column(String(300), primary_key=True)  # vault/name
    vault: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(127))
    app: Mapped[str] = mapped_column(String(40), index=True)
    env: Mapped[str] = mapped_column(String(5))
    last_rotated: Mapped[datetime | None]
    expires: Mapped[datetime | None]


class Cost(Base):
    __tablename__ = "costs"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    client: Mapped[str] = mapped_column(String(40), primary_key=True)
    usd: Mapped[float] = mapped_column(Float)


class AuditEvent(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    at: Mapped[datetime] = mapped_column(default=now, index=True)
    actor_kind: Mapped[str] = mapped_column(String(10))
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(300))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(10))


class Operation(Base):
    """Safe operations requested through the API, executed by the worker's `ops` job."""

    __tablename__ = "operations"
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    action: Mapped[str] = mapped_column(String(30))
    app: Mapped[str | None] = mapped_column(String(40))
    env: Mapped[str | None] = mapped_column(String(5))
    target: Mapped[str | None] = mapped_column(String(300))
    requested_by: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]


class WorkerRun(Base):
    __tablename__ = "worker_runs"
    job: Mapped[str] = mapped_column(String(30), primary_key=True)
    last_started: Mapped[datetime] = mapped_column(default=now)
    last_finished: Mapped[datetime | None]
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str | None] = mapped_column(Text)
