"""Sign-in with the client's own Entra ID. Only tokens from tenants in ALLOWED_TENANTS are accepted."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient


@dataclass(frozen=True)
class User:
    oid: str
    tid: str
    roles: tuple[str, ...]
    email: str = ""


def allowed_tenants() -> set[str]:
    return {t.strip() for t in os.environ.get("ALLOWED_TENANTS", "").split(",") if t.strip()}


@lru_cache
def _jwks() -> PyJWKClient:
    # Multi-tenant app: keys are shared across tenants; the tenant is checked from the claims below.
    return PyJWKClient("https://login.microsoftonline.com/common/discovery/v2.0/keys", cache_keys=True)


def verify(token: str, key=None) -> User:
    try:
        signing_key = key or _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, signing_key, algorithms=["RS256"], audience=os.environ["ENTRA_CLIENT_ID"],
                            options={"require": ["exp", "aud", "tid", "oid"]})
    except (jwt.PyJWTError, KeyError) as exc:
        raise HTTPException(401, "invalid token") from exc
    tid = claims["tid"]
    if tid not in allowed_tenants() or claims.get("iss") != f"https://login.microsoftonline.com/{tid}/v2.0":
        raise HTTPException(403, "this organization is not allowed to use the app")
    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    return User(oid=claims["oid"], tid=tid, roles=tuple(claims.get("roles", [])), email=email)


def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "sign in required")
    return verify(authorization.split(" ", 1)[1])
