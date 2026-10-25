"""One structured audit event per request into App Insights (and from there, Sentinel).

Identifies people by Entra object ID only. Never logs names, emails, request bodies, tax data or secrets.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request

log = logging.getLogger("app.audit")
SKIP = {"/healthz", "/readyz"}


async def audit_middleware(request: Request, call_next):
    if request.url.path in SKIP:
        return await call_next(request)
    started = time.perf_counter()
    response = await call_next(request)
    user = getattr(request.state, "user", None)
    status = response.status_code
    log.info(
        "audit",
        extra={
            "audit.oid": user.oid if user else "anonymous",
            "audit.tid": user.tid if user else "",
            "audit.action": request.method,
            "audit.resource": request.scope.get("route").path if request.scope.get("route") else request.url.path,
            "audit.source_ip": request.headers.get("x-forwarded-for", request.client.host if request.client else ""),
            "audit.result": "ok" if status < 400 else "denied" if status in (401, 403) else "error",
            "audit.status": status,
            "audit.ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return response
