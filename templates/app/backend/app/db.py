"""Postgres connections with the app's managed identity (Entra token as the password, never a stored one)."""

from __future__ import annotations

import os
from functools import lru_cache

from psycopg_pool import ConnectionPool

PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


@lru_cache
def _credential():
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID") or None)


def _password() -> str:
    if os.environ.get("PGPASSWORD"):  # local development only
        return os.environ["PGPASSWORD"]
    return _credential().get_token(PG_SCOPE).token


def _params() -> dict:
    """Called for every new connection, so each one gets a fresh token."""
    return {"host": os.environ["PGHOST"], "dbname": os.environ["PGDATABASE"], "user": os.environ["PGUSER"],
            "password": _password(), "sslmode": os.environ.get("PGSSLMODE", "require")}


@lru_cache
def pool() -> ConnectionPool:
    return ConnectionPool(kwargs=_params, min_size=1, max_size=5, max_lifetime=1800, open=True)
