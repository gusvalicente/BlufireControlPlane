import os
from pathlib import Path

import psycopg
import pytest

from app.auth import User
from app.identity import link

PG = os.environ.get("DBOPS_TEST_PGHOST")


@pytest.mark.skipif(not PG, reason="set DBOPS_TEST_PGHOST/PGPORT to run")
def test_link_on_first_sign_in():
    conn = psycopg.connect(host=PG, port=os.environ.get("DBOPS_TEST_PGPORT", "5432"), user="postgres", dbname="postgres",
                           autocommit=True)
    conn.execute("drop table if exists identity_map")
    conn.execute((Path(__file__).parents[1] / "migrations" / "0001_identity_map.sql").read_text())
    conn.execute("insert into identity_map(supabase_user_id, email) values ('7d3c3c8e-5a0b-4b55-9a49-9b5d3c1c1a11', 'Jane@Example.com')")
    u = User(oid="entra-1", tid="t1", roles=(), email="jane@example.com")
    assert link(conn, u) == "7d3c3c8e-5a0b-4b55-9a49-9b5d3c1c1a11"
    assert link(conn, u) == "7d3c3c8e-5a0b-4b55-9a49-9b5d3c1c1a11"
    other = User(oid="entra-2", tid="t1", roles=(), email="jane@example.com")
    assert link(conn, other) is None
