from datetime import UTC, date, datetime

from blufire_cp import changes as ch
from blufire_cp.auth import DEV_ADMIN
from blufire_cp.drift import compare
from blufire_cp.models import Backup, Drift, EnvStatus, Finding, Incident, Operation, RestoreTest, SecretMeta, WorkerRun
from blufire_cp.worker import jobs
from blufire_cp.worker.main import run_job

APP = "registry/apps/demo-cpa/intake-portal.yaml"
IMG = "acrblufire.azurecr.io/intake-fe@sha256:" + "a" * 64
IMG_BE = "acrblufire.azurecr.io/intake-be@sha256:" + "b" * 64


class FakeAzure:
    def __init__(self):
        self.started, self.secrets_set, self.restarted = [], [], []
        self.live = {}

    def log_query(self, ws, kql, timespan="P1D"):
        if "SecurityIncident" in kql:
            return [
                {
                    "IncidentNumber": 7,
                    "Title": "Suspicious sign-in",
                    "Severity": "High",
                    "Status": "New",
                    "CreatedTime": "2026-10-25T10:00:00Z",
                    "ClosedTime": None,
                    "IncidentUrl": "https://portal/x",
                }
            ]
        return [
            {
                "comp": "appi-demo-cpa-intake-portal-prod",
                "p95_ms": 412.0,
                "total": 1000,
                "failed": 1,
                "availability_pct": 99.98,
                "last_availability_ok": True,
            }
        ]

    def revisions(self, sub, rg, name):
        if not name.endswith("-prod"):
            raise FileNotFoundError(name)
        return [
            {
                "name": f"{name}--r1",
                "properties": {
                    "active": True,
                    "replicas": 1,
                    "healthState": "Healthy",
                    "createdTime": "2026-10-21T16:12:00Z",
                    "template": {"containers": [{"image": IMG}]},
                },
            }
        ]

    def resource_graph(self, q, subs):
        return [
            {
                "id": "/subscriptions/s/resourcegroups/rg-demo-cpa-intake-portal-prod/providers/x/assessments/1",
                "title": "Key Vault purge protection",
                "severity": "medium",
                "resourceId": "/subscriptions/s/resourcegroups/rg-demo-cpa-intake-portal-prod/providers/microsoft.keyvault/vaults/kv",
                "link": "https://portal/a",
            }
        ]

    def list_json_blobs(self, container, prefix=""):
        if container == "scan-results":
            trivy = {
                "Results": [
                    {
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": "CVE-2026-1187",
                                "PkgName": "openssl",
                                "InstalledVersion": "3.0.1",
                                "FixedVersion": "3.0.9",
                                "Severity": "CRITICAL",
                            }
                        ]
                    }
                ]
            }
            return [
                (
                    "intake-portal/prod/2026-10-24.json",
                    {
                        "client": "demo-cpa",
                        "app": "intake-portal",
                        "env": "prod",
                        "frontend": trivy,
                        "backend": {"Results": []},
                    },
                )
            ]
        return [
            (
                "intake-portal/prod/dump/20261025T060400Z.json",
                {
                    "kind": "dump",
                    "app": "intake-portal",
                    "env": "prod",
                    "layer": "nightly",
                    "blob": "pg-dumps/x.dump",
                    "size_bytes": 182000000,
                    "sha256": "abc",
                    "ok": True,
                    "finished_at": datetime.now(UTC).isoformat(),
                },
            ),
            (
                "intake-portal/prod/restore_test/20261003T070000Z.json",
                {
                    "kind": "restore_test",
                    "app": "intake-portal",
                    "env": "prod",
                    "ok": True,
                    "checks": ["schema", "row counts"],
                    "duration_s": 400,
                    "started_at": "2026-10-03T07:00:00Z",
                },
            ),
        ]

    def list_secret_meta(self, vault):
        return [{"name": "intake-portal-session-key", "updated": 1760000000, "exp": None}]

    def cost_month_to_date(self, sub):
        return 12.5

    def container_app(self, sub, rg, name):
        if name in self.live:
            return self.live[name]
        raise FileNotFoundError(name)

    digests: dict = {}

    def acr_digest(self, server, repo, tag):
        return self.digests.get(repo)

    def start_job(self, sub, rg, job, args):
        self.started.append((rg, job, args))
        return "exec-1"

    def set_secret(self, vault, name, value):
        self.secrets_set.append((vault, name))

    def restart_latest_revision(self, sub, rg, name):
        self.restarted.append(name)


def deploy_prod(ctx):
    patch = {
        "environments": {
            "prod": {
                "images": {"frontend": IMG, "backend": IMG_BE},
                "release": "v1.8.2",
                "secrets": ["intake-portal-session-key"],
            }
        }
    }
    c = ch.propose(ctx, ch.ChangeIn("Promote", APP, patch), DEV_ADMIN)
    ch.approve(ctx, c.id, DEV_ADMIN)


def test_health_rules():
    cfg = {"images": {"frontend": IMG}, "scale": {"min": 0, "max": 2}}
    alerts = {"latency_p95_ms": 1500, "error_rate_pct": 2}
    assert jobs.health({"images": {}, "scale": cfg["scale"]}, alerts, None, None)[0] == "not_deployed"
    assert jobs.health(cfg, alerts, None, 0)[0] == "scaled_to_zero"
    assert jobs.health(cfg, alerts, {"last_availability_ok": False}, 1)[0] == "down"
    assert jobs.health(cfg, alerts, {"p95_ms": 2000, "error_rate_pct": 0.1}, 1)[0] == "degraded"
    assert jobs.health(cfg, alerts, {"p95_ms": 400, "error_rate_pct": 0.1, "availability_pct": 99.9}, 1) == (
        "healthy",
        "Up 99.90%",
    )


def test_eol_findings(ctx):
    found = jobs.eol_findings(ctx.snapshot(), date(2027, 3, 1))
    assert [f.id for f in found] == ["runtime_eol/intake-portal/node"]


def test_sync_pulls_everything(ctx, monkeypatch):
    deploy_prod(ctx)
    ctx.azure = FakeAzure()
    monkeypatch.setattr(jobs, "_settings", lambda: type("S", (), {"log_analytics_workspace_id": "ws"})())
    assert jobs.sync(ctx) == "synced"
    with ctx.sessions() as s:
        prod = s.get(EnvStatus, ("intake-portal", "prod"))
        assert prod.health == "healthy" and prod.summary == "Up 99.98%" and prod.replicas_current == 1
        assert s.get(Incident, "sentinel/7").severity == "p1"
        sev = {f.source: f.severity for f in s.query(Finding).all()}
        assert sev["trivy"] == "critical" and sev["defender"] == "medium"
        assert s.query(Backup).count() == 1 and s.query(RestoreTest).count() == 1
        assert s.get(SecretMeta, "kv-demo-cpa-p-05d1/intake-portal-session-key").last_rotated is not None


def test_findings_resolve_when_gone(ctx):
    with ctx.sessions() as s:
        jobs.upsert_findings(
            s, "trivy", [Finding(id="t1", source="trivy", app="a", env="prod", title="x", severity="high")], "a", "prod"
        )
        s.commit()
        jobs.upsert_findings(s, "trivy", [], "a", "prod")
        s.commit()
        assert s.get(Finding, "t1").status == "resolved"


def test_drift_check_records_and_resolves(ctx):
    deploy_prod(ctx)
    az = FakeAzure()
    live = {
        "properties": {
            "template": {
                "scale": {"minReplicas": 1, "maxReplicas": 10},
                "containers": [{"image": IMG_BE, "env": [{"name": "LOG_LEVEL", "value": "warning"}]}],
            },
            "configuration": {"ingress": {}},
        }
    }
    az.live["ca-intake-portal-be-prod"] = live
    ctx.azure = az
    assert jobs.drift_check(ctx) == "1 new drift item(s)"
    live["properties"]["template"]["scale"]["maxReplicas"] = 3
    jobs.drift_check(ctx)
    with ctx.sessions() as s:
        assert s.get(Drift, "ca-intake-portal-be-prod|scale.maxReplicas").status == "reverted"


def test_drift_compare_origins():
    cfg = {
        "scale": {"min": 1, "max": 3},
        "origins": {"enabled": True, "cidrs": [{"cidr": "203.0.113.0/24", "label": "VPN"}]},
    }
    live = {
        "properties": {
            "template": {"scale": {"minReplicas": 1, "maxReplicas": 3}, "containers": [{}]},
            "configuration": {
                "ingress": {"ipSecurityRestrictions": [{"ipAddressRange": "203.0.113.0/24", "action": "Allow"}]}
            },
        }
    }
    items = compare("fe", "frontend", cfg, live, "192.0.2.17/32")
    assert [i.property for i in items] == ["ingress.ipSecurityRestrictions"]
    live["properties"]["configuration"]["ingress"]["ipSecurityRestrictions"].append({"ipAddressRange": "192.0.2.17/32"})
    assert compare("fe", "frontend", cfg, live, "192.0.2.17/32") == []


def test_nightly_backup_starts_dbops_and_flags_late(ctx, monkeypatch):
    deploy_prod(ctx)
    az = FakeAzure()
    ctx.azure = az
    events = []
    monkeypatch.setattr(jobs, "event", lambda name, **d: events.append((name, d)))
    jobs.nightly_backup(ctx)
    jobs_started = [j for _, j, _ in az.started]
    assert "caj-demo-cpa-dbops-prod" in jobs_started and "caj-platform-dbops" in jobs_started
    assert (
        "backup_failed",
        {"app": "intake-portal", "env": "prod", "detail": "no successful nightly dump in 26 hours"},
    ) in events


def test_dev_bump_from_acr(ctx):
    az = FakeAzure()
    az.digests = {
        "demo-cpa/intake-portal-frontend": "sha256:" + "c" * 64,
        "demo-cpa/intake-portal-backend": "sha256:" + "d" * 64,
    }
    ctx.azure = az
    assert jobs.dev_bump(ctx) == 1
    dev = ctx.snapshot(fresh=True).apps["intake-portal"]["environments"]["dev"]
    assert dev["images"]["backend"].endswith("@sha256:" + "d" * 64) and dev["release"] == "dev-ddddddd"
    assert jobs.dev_bump(ctx) == 0  # already deployed
    from blufire_cp.models import Change

    with ctx.sessions() as s:
        c = s.query(Change).filter(Change.actor_kind == "ci").one()
        assert c.status == "applied" and c.risk == "low"


def test_ops_queue(ctx):
    deploy_prod(ctx)
    az = FakeAzure()
    ctx.azure = az
    with ctx.sessions() as s:
        s.add_all(
            [
                Operation(action="backup", app="intake-portal", env="prod", requested_by="Gus"),
                Operation(action="scan", requested_by="Claude"),
                Operation(
                    action="secret_rotate",
                    app="intake-portal",
                    env="prod",
                    target="kv-demo-cpa-p-05d1/intake-portal-session-key",
                    requested_by="Gus",
                ),
                Operation(action="backup", requested_by="Gus"),
            ]
        )
        s.commit()
    assert jobs.ops(ctx) == "4 operation(s)"
    with ctx.sessions() as s:
        statuses = sorted(o.status for o in s.query(Operation).all())
    assert statuses == ["done", "done", "done", "failed"]
    assert az.secrets_set == [("kv-demo-cpa-p-05d1", "intake-portal-session-key")]
    assert ctx.store.dispatched == [("nightly-image-scan.yml", {})]


def test_run_job_records_heartbeat(ctx):
    assert run_job(ctx, "sync") == 0
    with ctx.sessions() as s:
        assert s.get(WorkerRun, "sync").ok
