from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Request

from .audit import audit_middleware
from .auth import User, current_user

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="app")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())

app = FastAPI(title=os.environ.get("APP_ID", "app"), docs_url=None, redoc_url=None)
app.middleware("http")(audit_middleware)


def user(request: Request, u: Annotated[User, Depends(current_user)]) -> User:
    request.state.user = u
    return u


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    from .db import pool

    with pool().connection() as conn:
        conn.execute("select 1")
    return {"ok": True}


@app.get("/api/me")
def me(u: Annotated[User, Depends(user)]):
    return {"oid": u.oid, "tenant": u.tid, "roles": list(u.roles)}
