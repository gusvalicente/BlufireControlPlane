"""State database engine. In Azure the managed identity signs in to Postgres with an Entra token (no password)."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings
from .models import Base

PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def make_engine(url: str | None = None) -> Engine:
    s = settings()
    url = url or s.state_db_url
    if url:
        kw = {}
        if url.startswith("sqlite"):
            kw = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        return create_engine(url, **kw)
    if s.dev_mode:
        return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential(managed_identity_client_id=s.azure_client_id or None)
    engine = create_engine(
        f"postgresql+psycopg://{s.state_db_user}@{s.state_db_host}:5432/{s.state_db_name}",
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
        pool_recycle=1800,
    )

    @event.listens_for(engine, "do_connect")
    def _token(dialect, conn_rec, cargs, cparams):  # noqa: ARG001
        cparams["password"] = credential.get_token(PG_SCOPE).token

    return engine


def make_sessions(url: str | None = None) -> sessionmaker[Session]:
    eng = make_engine(url)
    Base.metadata.create_all(eng)
    return sessionmaker(eng, expire_on_commit=False)
