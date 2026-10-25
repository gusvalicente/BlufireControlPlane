import pytest

from blufire_cp import changes as ch
from blufire_cp.auth import DEV_ADMIN, DEV_AGENT
from blufire_cp.gitstore import ConflictError

APP = "registry/apps/demo-cpa/intake-portal.yaml"


def test_low_risk_commits_directly(ctx):
    c = ch.propose(ctx, ch.ChangeIn("Raise dev max", APP, {"environments": {"dev": {"scale": {"max": 3}}}}), DEV_ADMIN)
    assert c.status == "applied" and c.risk == "low" and c.commit_sha
    assert "max: 3" in ctx.store.read_file(APP)[0]
    assert "-    scale: {min: 0, max: 2}" in c.diff or "max: 2" in c.diff


def test_prod_change_opens_pr_and_approve_merges(ctx):
    patch = {
        "environments": {"prod": {"origins": {"enabled": True, "cidrs": [{"cidr": "203.0.113.0/24", "label": "VPN"}]}}}
    }
    c = ch.propose(ctx, ch.ChangeIn("Enable origins", APP, patch), DEV_ADMIN)
    assert c.status == "pending" and c.pr_number and c.risk == "approval"
    assert "203.0.113.0/24" not in ctx.store.read_file(APP)[0]
    done = ch.approve(ctx, c.id, DEV_ADMIN)
    assert done.status == "applied"
    assert "203.0.113.0/24" in ctx.store.read_file(APP)[0]


def test_reject_closes_pr(ctx):
    c = ch.propose(ctx, ch.ChangeIn("Prod scale", APP, {"environments": {"prod": {"scale": {"max": 5}}}}), DEV_ADMIN)
    r = ch.reject(ctx, c.id, DEV_ADMIN, "not now")
    assert r.status == "rejected" and ctx.store.prs[c.pr_number].state == "closed"
    with pytest.raises(ch.ChangeError):
        ch.approve(ctx, c.id, DEV_ADMIN)


def test_agent_always_needs_approval(ctx):
    c = ch.propose(ctx, ch.ChangeIn("Tune alert", APP, {"alerts": {"latency_p95_ms": 1800}}), DEV_AGENT)
    assert c.status == "pending" and c.matched_rules == ["actor:agent"]


def test_schema_and_rule_errors_block_change(ctx):
    with pytest.raises(ch.ChangeError) as e:
        ch.propose(ctx, ch.ChangeIn("Bad", APP, {"environments": {"dev": {"scale": {"max": 99}}}}), DEV_ADMIN)
    assert e.value.status == 422
    with pytest.raises(ch.ChangeError) as e:
        ch.propose(
            ctx, ch.ChangeIn("No cidrs", APP, {"environments": {"dev": {"origins": {"enabled": True}}}}), DEV_ADMIN
        )
    assert "would block the client" in e.value.message


def test_conflict_when_file_changed(ctx, monkeypatch):
    def boom(*a, **k):
        raise ConflictError("stale")

    monkeypatch.setattr(ctx.store, "commit_file", boom)
    with pytest.raises(ch.ChangeError) as e:
        ch.propose(ctx, ch.ChangeIn("Raise", APP, {"environments": {"dev": {"scale": {"max": 3}}}}), DEV_ADMIN)
    assert e.value.status == 409


def test_cannot_edit_outside_registry(ctx):
    with pytest.raises(ch.ChangeError):
        ch.propose(ctx, ch.ChangeIn("Sneaky", ".github/workflows/ci.yml", {"x": 1}), DEV_ADMIN)


def test_graduation_updates_client_and_app_in_one_pr(ctx):
    sub = "44444444-4444-4444-4444-444444444444"
    c = ch.propose_graduation(ctx, "ap-portal", sub, DEV_ADMIN)
    assert c.status == "pending" and "registry/clients/demo-tax.yaml" in c.diff
    ch.approve(ctx, c.id, DEV_ADMIN)
    snap = ctx.snapshot(fresh=True)
    assert snap.apps["ap-portal"]["stage"] == "graduated"
    assert snap.clients["demo-tax"]["subscription_id"] == sub


def test_drift_patch_mapping():
    assert ch.drift_patch("ca-x-y-be-prod", "scale.maxReplicas", "prod", "10") == {
        "environments": {"prod": {"scale": {"max": 10}}}
    }
    assert ch.drift_patch("ca-x-y-fe-dev", "image", "dev", "acr/x@sha256:" + "a" * 64)["environments"]["dev"][
        "images"
    ] == {"frontend": "acr/x@sha256:" + "a" * 64}
