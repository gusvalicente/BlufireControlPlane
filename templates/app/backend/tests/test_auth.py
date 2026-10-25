import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app import auth

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
GOOD, OTHER = "11111111-1111-1111-1111-111111111111", "99999999-9999-9999-9999-999999999999"


def token(tid=GOOD, aud="app-client"):
    t = int(time.time())
    return jwt.encode({"iss": f"https://login.microsoftonline.com/{tid}/v2.0", "tid": tid, "oid": "u1", "aud": aud,
                       "iat": t, "exp": t + 300}, KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("ENTRA_CLIENT_ID", "app-client")
    monkeypatch.setenv("ALLOWED_TENANTS", GOOD)


def test_allowed_tenant():
    assert auth.verify(token(), KEY.public_key()).tid == GOOD


def test_other_tenant_rejected():
    with pytest.raises(HTTPException) as e:
        auth.verify(token(OTHER), KEY.public_key())
    assert e.value.status_code == 403


def test_wrong_audience_rejected():
    with pytest.raises(HTTPException) as e:
        auth.verify(token(aud="x"), KEY.public_key())
    assert e.value.status_code == 401


def test_email_claim_is_lowercased():
    t = int(time.time())
    tok = jwt.encode({"iss": f"https://login.microsoftonline.com/{GOOD}/v2.0", "tid": GOOD, "oid": "u1", "aud": "app-client",
                      "iat": t, "exp": t + 300, "preferred_username": "Jane@Example.com"}, KEY, algorithm="RS256")
    assert auth.verify(tok, KEY.public_key()).email == "jane@example.com"
