"""Apply migrations/*.sql in name order, once each. Runs at container start (see Dockerfile); an advisory lock
keeps two replicas from migrating at the same time."""

from __future__ import annotations

from pathlib import Path

from .db import pool

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def main() -> None:
    with pool().connection() as conn:
        conn.execute("select pg_advisory_lock(727274)")
        conn.execute("create table if not exists schema_migrations (name text primary key, applied_at timestamptz default now())")
        done = {r[0] for r in conn.execute("select name from schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("insert into schema_migrations(name) values (%s)", (path.name,))
            print(f"applied {path.name}")
        conn.execute("select pg_advisory_unlock(727274)")
    pool().close()


if __name__ == "__main__":
    main()
