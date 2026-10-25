"""db-ops: pure helpers always; dump and restore-test end to end when DBOPS_TEST_PGHOST points at a Postgres."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dbops"))
import blufire_dbops as d  # noqa: E402


def test_safe_name():
    assert d.safe_name("intake_portal_prod") == "intake_portal_prod"
    for bad in ('x"; drop', "Upper", "", "a" * 70, "1abc"):
        with pytest.raises(d.DbopsError):
            d.safe_name(bad)


def test_compare_counts():
    assert d.compare_counts({"public.a": 1}, {"public.a": 1}) == []
    assert d.compare_counts({"public.a": 1, "public.b": 2}, {"public.a": 3, "public.c": 0}) == [
        "public.a: expected 1 rows, found 3",
        "missing table public.b",
        "unexpected table public.c",
    ]


def test_drop_refused_outside_sandbox(monkeypatch):
    monkeypatch.delenv("DBOPS_ALLOW_DROP", raising=False)
    assert d.main(["drop-database", "--database", "anything"]) == 1


class FolderContainer:
    """Stands in for a blob container, backed by a local folder."""

    class _Blob:
        def __init__(self, name):
            self.name = name

    class _Download:
        def __init__(self, data):
            self.data = data

        def readall(self):
            return self.data

    def __init__(self, root: Path):
        self.root = root

    def upload_blob(self, name, data, metadata=None):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.read() if hasattr(data, "read") else data.encode() if isinstance(data, str) else data)

    def download_blob(self, name):
        return self._Download((self.root / name).read_bytes())

    def list_blobs(self, name_starts_with=""):
        return [
            self._Blob(str(p.relative_to(self.root)))
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and str(p.relative_to(self.root)).startswith(name_starts_with)
        ]


@pytest.mark.skipif(not os.environ.get("DBOPS_TEST_PGHOST"), reason="set DBOPS_TEST_PGHOST/PGPORT/PGUSER to run")
def test_dump_and_restore_test_end_to_end(tmp_path, monkeypatch):
    env = {
        **os.environ,
        "PGHOST": os.environ["DBOPS_TEST_PGHOST"],
        "PGPORT": os.environ.get("DBOPS_TEST_PGPORT", "5432"),
        "PGUSER": os.environ.get("DBOPS_TEST_PGUSER", "postgres"),
    }
    subprocess.run(["psql", "-d", "postgres", "-c", "drop database if exists app_prod"], env=env, check=True)
    subprocess.run(["psql", "-d", "postgres", "-c", "create database app_prod"], env=env, check=True)
    subprocess.run(
        [
            "psql",
            "-d",
            "app_prod",
            "-c",
            "create table clients(id int); insert into clients select generate_series(1,25);"
            "create schema intake; create table intake.forms(id int); insert into intake.forms values (1),(2);",
        ],
        env=env,
        check=True,
    )
    containers = {}
    monkeypatch.setattr(d, "_pg_env", lambda: env)
    monkeypatch.setattr(d, "_container", lambda n: containers.setdefault(n, FolderContainer(tmp_path / n)))

    assert d.main(["dump", "--app", "intake", "--env", "prod", "--database", "app_prod", "--layer", "nightly"]) == 0
    results = sorted((tmp_path / "dbops-results").rglob("*.json"))
    dump = json.loads(results[-1].read_text())
    assert dump["ok"] and dump["tables"] == 2 and dump["size_bytes"] > 0

    assert d.main(["restore-test", "--app", "intake", "--env", "prod", "--database", "app_prod"]) == 0
    test = json.loads(
        sorted((tmp_path / "dbops-results" / "intake" / "prod" / "restore_test").glob("*.json"))[-1].read_text()
    )
    assert test["ok"] and "row counts match" in test["checks"]
    left = subprocess.run(
        ["psql", "-d", "postgres", "-At", "-c", "select count(*) from pg_database where datname like 'restoretest_%'"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert left == "0"


def test_filter_toc_drops_supabase_only_objects():
    toc = (
        "; Archive created at 2026-10-25\n"
        "215; 1259 16400 TABLE public clients postgres\n"
        "3401; 3256 16410 POLICY public clients owner_only postgres\n"
        "3402; 0 0 ROW SECURITY public clients postgres\n"
        "2; 3079 16384 EXTENSION - pgcrypto \n"
        "3403; 0 0 COMMENT - EXTENSION pgcrypto \n"
        "3300; 0 16400 TABLE DATA public clients postgres\n"
    )
    kept = d.filter_toc(toc)
    assert "TABLE public clients" in kept and "TABLE DATA" in kept
    assert "POLICY" not in kept and "ROW SECURITY" not in kept and "EXTENSION" not in kept


@pytest.mark.skipif(not os.environ.get("DBOPS_TEST_PGHOST"), reason="set DBOPS_TEST_PGHOST/PGPORT/PGUSER to run")
def test_migrate_skips_policies_that_reference_supabase(tmp_path, monkeypatch):
    env = {
        **os.environ,
        "PGHOST": os.environ["DBOPS_TEST_PGHOST"],
        "PGPORT": os.environ.get("DBOPS_TEST_PGPORT", "5432"),
        "PGUSER": os.environ.get("DBOPS_TEST_PGUSER", "postgres"),
    }
    for db in ("supa_src", "azure_dst"):
        subprocess.run(["psql", "-d", "postgres", "-c", f"drop database if exists {db}"], env=env, check=True)
        subprocess.run(["psql", "-d", "postgres", "-c", f"create database {db}"], env=env, check=True)
    subprocess.run(
        [
            "psql",
            "-d",
            "supa_src",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "create schema auth; create function auth.uid() returns uuid language sql as 'select null::uuid';"
            "create table public.forms(id int, owner uuid); insert into public.forms values (1, null), (2, null);"
            "alter table public.forms enable row level security;"
            "create policy owner_only on public.forms using (owner = auth.uid());",
        ],
        env=env,
        check=True,
    )
    (tmp_path / "migrations").mkdir()
    subprocess.run(
        [
            "pg_dump",
            "-Fc",
            "--no-owner",
            "--no-privileges",
            "-n",
            "public",
            "-d",
            "supa_src",
            "-f",
            str(tmp_path / "migrations" / "app.dump"),
        ],
        env=env,
        check=True,
    )
    containers = {}
    monkeypatch.setattr(d, "_pg_env", lambda: env)
    monkeypatch.setattr(d, "_container", lambda n: containers.setdefault(n, FolderContainer(tmp_path / n)))
    assert d.main(["migrate-from-blob", "--blob", "app.dump", "--database", "azure_dst"]) == 1
    subprocess.run(["psql", "-d", "postgres", "-c", "drop database azure_dst"], env=env, check=True)
    subprocess.run(["psql", "-d", "postgres", "-c", "create database azure_dst"], env=env, check=True)
    assert (
        d.main(["migrate-from-blob", "--blob", "app.dump", "--database", "azure_dst", "--skip-supabase-objects"]) == 0
    )
    rows = subprocess.run(
        ["psql", "-d", "azure_dst", "-At", "-c", "select count(*) from public.forms"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert rows == "2"
