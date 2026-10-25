"""Entra ID token validation, roles and step-up MFA."""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient

from .config import Settings

ADMIN, AGENT = "Admin", "Agent"


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Principal:
    oid: str
    name: str
    roles: tuple[str, ...]
    claims: dict

    @property
    def kind(self) -> str:
        if ADMIN in self.roles:
            return "admin"
        return "agent" if AGENT in self.roles else "ci" if "CI" in self.roles else "none"


@lru_cache(maxsize=4)
def _jwks(tenant_id: str) -> PyJWKClient:
    return PyJWKClient(f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys", cache_keys=True)


def _issuers(tenant_id: str) -> list[str]:
    return [f"https://login.microsoftonline.com/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"]


def decode(token: str, audiences: list[str], s: Settings, key=None) -> dict:
    """Validate signature, issuer, audience and expiry. `key` is injectable for tests."""
    try:
        signing_key = key or _jwks(s.tenant_id).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, signing_key, algorithms=["RS256"], audience=audiences, options={"require": ["exp", "iat", "aud"]}
        )
    except jwt.PyJWTError as exc:
        raise AuthError(401, "invalid_token", f"token rejected: {exc}") from exc
    if claims.get("iss") not in _issuers(s.tenant_id):
        raise AuthError(401, "invalid_token", "unexpected issuer")
    if claims.get("tid") != s.tenant_id:
        raise AuthError(401, "invalid_token", "token from another tenant")
    return claims


def principal_from_token(token: str, s: Settings, key=None) -> Principal:
    claims = decode(token, [a for a in s.api_audience.split(",") if a], s, key)
    roles = tuple(claims.get("roles", []))
    if not roles:
        raise AuthError(403, "no_role", "caller has no Admin or Agent role on platform-api")
    name = (
        claims.get("name") or claims.get("preferred_username") or claims.get("app_displayname") or claims.get("azp", "")
    )
    return Principal(oid=claims.get("oid", ""), name=name, roles=roles, claims=claims)


def require_step_up(p: Principal, step_up_token: str | None, s: Settings, key=None, now: float | None = None) -> None:
    """Approvals need a fresh MFA sign-in: an ID token from the UI no older than step_up_max_age_s."""
    if s.step_up_acrs and s.step_up_acrs in p.claims.get("acrs", []):
        return
    if not step_up_token:
        raise AuthError(403, "step_up_required", "sign in again with MFA to approve")
    claims = decode(step_up_token, [s.ui_client_id], s, key)
    now = now or time.time()
    fresh = now - float(claims.get("auth_time", 0)) <= s.step_up_max_age_s
    # Entra v2 ID tokens usually omit amr. The BluFire tenant must require MFA on every sign-in (Conditional Access
    # or security defaults), so a fresh interactive sign-in implies MFA; when amr is present it must say so.
    amr_ok = "amr" not in claims or "mfa" in claims["amr"]
    if claims.get("oid") != p.oid or not amr_ok or not fresh:
        raise AuthError(403, "step_up_required", "sign in again with MFA to approve")


DEV_ADMIN = Principal(oid="dev-gus", name="Gus (dev)", roles=(ADMIN,), claims={"amr": ["mfa"]})
# The worker acting on behalf of app build pipelines (dev image bumps only). Never reachable through the API.
CI = Principal(oid="ci", name="build pipeline", roles=("CI",), claims={})
DEV_AGENT = Principal(oid="dev-agent", name="Claude (dev)", roles=(AGENT,), claims={})
