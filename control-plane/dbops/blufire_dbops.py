"""blufire-dbops: database jobs that must run inside a private Postgres network.

Runs as a Container Apps Job next to each Postgres server. Signs in to Postgres and Blob Storage with its
managed identity (no passwords). Every command writes a result file the platform worker ingests:
dbops-results/<app>/<env>/<kind>/<UTC timestamp>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ROW_COUNTS_SQL = """
select n.nspname || '.' || c.relname
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relkind = 'r' and n.nspname not in ('pg_catalog', 'information_schema') and n.nspname not like 'pg_toast%'
order by 1
"""


class DbopsError(Exception):
    pass


# ---------------------------------------------------------------- pure helpers (unit tested)
def safe_name(value: str) -> str:
    if not NAME.match(value):
        raise DbopsError(f"refusing unsafe database or role name: {value!r}")
    return value


def compare_counts(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    """Human-readable differences between two {table: row_count} maps. Empty list = match."""
    problems = []
    for table in sorted(set(expected) | set(actual)):
        if table not in actual:
            problems.append(f"missing table {table}")
        elif table not in expected:
            problems.append(f"unexpected table {table}")
        elif expected[table] != actual[table]:
            problems.append(f"{table}: expected {expected[table]} rows, found {actual[table]}")
    return problems


SUPABASE_ONLY = (
    " POLICY ",
    " ROW SECURITY ",
    " EXTENSION ",
    " COMMENT - EXTENSION ",
    " SCHEMA - public ",
    " COMMENT - SCHEMA public ",
)


def filter_toc(toc: str) -> str:
    """Drop objects that break a restore of a Supabase dump: RLS policies that call auth.uid(), extensions
    (enable needed ones on Azure through the azure.extensions server parameter) and CREATE SCHEMA public."""
    return "".join(line for line in toc.splitlines(keepends=True) if not any(k in line for k in SUPABASE_ONLY))


def blob_path(app: str, env: str, kind: str, at: datetime, ext: str) -> str:
    return f"{app}/{env}/{kind}/{at:%Y%m%dT%H%M%SZ}.{ext}"


# ---------------------------------------------------------------- Azure plumbing
def _credential():
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID") or None)


def _container(name: str):
    from azure.storage.blob import BlobServiceClient

    account = os.environ["BACKUP_STORAGE_ACCOUNT"]
    svc = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=_credential())
    return svc.get_container_client(name)


def _pg_env() -> dict[str, str]:
    token = _credential().get_token(PG_SCOPE).token
    return {**os.environ, "PGPASSWORD": token, "PGSSLMODE": "require", "PGPORT": os.environ.get("PGPORT", "5432")}


def _run(cmd: list[str], env: dict[str, str]) -> str:
    out = subprocess.run(cmd, env=env, capture_output=True, text=True)  # noqa: S603 - fixed argv, no shell
    if out.returncode:
        raise DbopsError(f"{cmd[0]} failed: {out.stderr.strip()[:800]}")
    return out.stdout


def _psql(db: str, sql: str, env: dict[str, str]) -> str:
    return _run(["psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql], env)


def row_counts(db: str, env: dict[str, str]) -> dict[str, int]:
    tables = [t for t in _psql(db, ROW_COUNTS_SQL, env).splitlines() if t]
    counts = {}
    for t in tables:
        schema, table = t.split(".", 1)
        ident = ".".join('"' + part.replace('"', '""') + '"' for part in (schema, table))
        counts[t] = int(_psql(db, f"select count(*) from {ident}", env).strip())  # noqa: S608 - quoted identifiers
    return counts


def _write_result(app: str, env_name: str, kind: str, data: dict) -> str:
    at = datetime.now(UTC)
    path = blob_path(app, env_name, kind, at, "json")
    body = {"kind": kind, "app": app, "env": env_name, "finished_at": at.isoformat(), **data}
    _container(os.environ.get("RESULT_CONTAINER", "dbops-results")).upload_blob(path, json.dumps(body, indent=2))
    print(json.dumps(body))
    return path


def _dump_container(layer: str) -> str:
    """Override per layer with BACKUP_CONTAINER_<LAYER> (e.g. BACKUP_CONTAINER_PRE_PROMOTION)."""
    return os.environ.get(f"BACKUP_CONTAINER_{layer.upper()}", os.environ.get("BACKUP_CONTAINER", "pg-dumps"))


# ---------------------------------------------------------------- commands
def cmd_dump(a) -> None:
    db, env = safe_name(a.database), _pg_env()
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{db}.dump"
        _run(["pg_dump", "-Fc", "--no-owner", "--no-privileges", "-d", db, "-f", str(out)], env)
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        path = blob_path(a.app, a.env, a.layer, datetime.now(UTC), "dump")
        container = _container(_dump_container(a.layer))
        with out.open("rb") as fh:
            container.upload_blob(path, fh, metadata={"sha256": digest, "database": db, "layer": a.layer})
        counts = row_counts(db, env)
        container.upload_blob(f"{path}.manifest.json", json.dumps({"sha256": digest, "row_counts": counts}))
        size = out.stat().st_size
    _write_result(
        a.app,
        a.env,
        "dump",
        {
            "ok": True,
            "layer": a.layer,
            "blob": f"{_dump_container(a.layer)}/{path}",
            "size_bytes": size,
            "sha256": digest,
            "duration_s": round(time.time() - started, 1),
            "tables": len(counts),
        },
    )


def _latest_dump(app: str, env_name: str, layers=("nightly", "manual", "pre_promotion")) -> tuple[str, str]:
    best = None
    for layer in layers:
        container_name = _dump_container(layer)
        for blob in _container(container_name).list_blobs(name_starts_with=f"{app}/{env_name}/{layer}/"):
            if blob.name.endswith(".dump") and (
                best is None or blob.name.rsplit("/", 1)[-1] > best[1].rsplit("/", 1)[-1]
            ):
                best = (container_name, blob.name)
    if not best:
        raise DbopsError(f"no dump found for {app} {env_name}")
    return best


def _restore(container_name: str, blob: str, db: str, env: dict[str, str], skip_supabase: bool = False) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "in.dump"
        local.write_bytes(_container(container_name).download_blob(blob).readall())
        cmd = ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "-d", db]
        if skip_supabase:
            toc = Path(tmp) / "toc.list"
            toc.write_text(filter_toc(_run(["pg_restore", "-l", str(local)], env)))
            cmd += ["-L", str(toc)]
        _run([*cmd, str(local)], env)


def cmd_restore_test(a) -> None:
    env, started = _pg_env(), time.time()
    container_name, blob = _latest_dump(a.app, a.env)
    manifest = json.loads(_container(container_name).download_blob(f"{blob}.manifest.json").readall())
    temp = safe_name(f"restoretest_{int(started)}")
    checks, ok, detail = [], False, ""
    try:
        _psql("postgres", f'create database "{temp}"', env)
        _restore(container_name, blob, temp, env)
        checks.append("pg_restore completed")
        problems = compare_counts(manifest["row_counts"], row_counts(temp, env))
        checks.append(f"{len(manifest['row_counts'])} tables compared")
        ok, detail = not problems, "; ".join(problems[:10])
        if ok:
            checks.append("row counts match")
    except DbopsError as exc:
        detail = str(exc)
    finally:
        _psql("postgres", f'drop database if exists "{temp}" with (force)', env)
    _write_result(
        a.app,
        a.env,
        "restore_test",
        {
            "ok": ok,
            "source_blob": f"{container_name}/{blob}",
            "checks": checks,
            "detail": detail,
            "started_at": datetime.fromtimestamp(started, UTC).isoformat(),
            "duration_s": round(time.time() - started, 1),
        },
    )
    if not ok:
        raise DbopsError(f"restore test failed: {detail}")


def cmd_drop_database(a) -> None:
    if os.environ.get("DBOPS_ALLOW_DROP") != "1":
        raise DbopsError("drop-database is only allowed on the sandbox db-ops job")
    db = safe_name(a.database)
    _psql("postgres", f'drop database if exists "{db}" with (force)', _pg_env())
    _write_result("sandbox", "dev", "drop", {"ok": True, "database": db})


def cmd_grant(a) -> None:
    """Create the database if missing and give an app's managed identity owner-level rights on it."""
    db, principal, env = safe_name(a.database), a.principal, _pg_env()
    if not re.match(r"^[A-Za-z0-9-]{1,120}$", principal):
        raise DbopsError(f"refusing unsafe principal name {principal!r}")
    # db and principal are validated against strict patterns above, so interpolation is safe here.
    if not _psql("postgres", f"select 1 from pg_database where datname = '{db}'", env).strip():  # noqa: S608
        _psql("postgres", f'create database "{db}"', env)
    if not _psql("postgres", f"select 1 from pg_roles where rolname = '{principal}'", env).strip():  # noqa: S608
        _psql("postgres", f"select * from pgaadauth_create_principal('{principal}', false, false)", env)  # noqa: S608
    _psql("postgres", f'grant all privileges on database "{db}" to "{principal}"', env)
    _psql(db, f'grant all on schema public to "{principal}"; alter schema public owner to "{principal}"', env)
    _write_result(a.app or "platform", a.env or "prod", "grant", {"ok": True, "database": db, "principal": principal})


def cmd_migrate_from_blob(a) -> None:
    """Restore a pg_dump (custom format) that Gus uploaded to the migrations container."""
    db, env = safe_name(a.database), _pg_env()
    _restore("migrations", a.blob, db, env, skip_supabase=a.skip_supabase_objects)
    counts = row_counts(db, env)
    _write_result(a.app or "migration", a.env or "prod", "migrate", {"ok": True, "blob": a.blob, "row_counts": counts})


def cmd_run_sql(a) -> None:
    """Run a .sql file from the migrations container (for example the identity_map seed from the export script)."""
    db, env = safe_name(a.database), _pg_env()
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "in.sql"
        local.write_bytes(_container("migrations").download_blob(a.blob).readall())
        _run(["psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(local)], env)
    _write_result(a.app or "migration", a.env or "prod", "run_sql", {"ok": True, "blob": a.blob})


def cmd_verify(a) -> None:
    """Compare row counts with an expected-counts JSON ({table: count}) in the migrations container."""
    db, env = safe_name(a.database), _pg_env()
    expected = json.loads(_container("migrations").download_blob(a.expect).readall())
    problems = compare_counts(expected, row_counts(db, env))
    _write_result(a.app or "migration", a.env or "prod", "verify", {"ok": not problems, "problems": problems})
    if problems:
        raise DbopsError("; ".join(problems[:10]))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="blufire-dbops")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("dump", "restore-test", "drop-database", "grant", "migrate-from-blob", "run-sql", "verify"):
        s = sub.add_parser(name)
        s.add_argument("--app", default=None)
        s.add_argument("--env", default=None, choices=["dev", "cert", "prod"])
        s.add_argument("--database", required=True)
        if name == "dump":
            s.add_argument("--layer", default="nightly", choices=["nightly", "pre_promotion", "manual"])
        if name == "grant":
            s.add_argument("--principal", required=True)
        if name in ("migrate-from-blob", "run-sql"):
            s.add_argument("--blob", required=True)
        if name == "migrate-from-blob":
            s.add_argument("--skip-supabase-objects", action="store_true")
        if name == "verify":
            s.add_argument("--expect", required=True)
    a = p.parse_args(argv)
    if a.cmd in ("dump", "restore-test") and not (a.app and a.env):
        p.error("--app and --env are required")
    handler = {
        "dump": cmd_dump,
        "restore-test": cmd_restore_test,
        "drop-database": cmd_drop_database,
        "grant": cmd_grant,
        "migrate-from-blob": cmd_migrate_from_blob,
        "run-sql": cmd_run_sql,
        "verify": cmd_verify,
    }[a.cmd]
    try:
        handler(a)
    except DbopsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if a.cmd == "dump":
            try:
                _write_result(a.app, a.env, "dump", {"ok": False, "layer": a.layer, "detail": str(exc)})
            except Exception as write_exc:  # storage may be the thing that failed
                print(f"could not write failure result: {write_exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
