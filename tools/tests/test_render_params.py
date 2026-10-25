import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("render_params", ROOT / "tools/render_params.py")
rp = importlib.util.module_from_spec(_spec)
sys.modules["render_params"] = rp
_spec.loader.exec_module(rp)

DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def repo(tmp_path):
    for rel in ("platform.yaml", "registry", "alerts", "infra/platform-settings.json", "infra/platform-images.json"):
        src = ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy(src, dst)
    return tmp_path


def app_path(root, client, app):
    return root / "registry/apps" / client / f"{app}.yaml"


def edit_yaml(path, fn):
    doc = yaml.safe_load(path.read_text())
    fn(doc)
    path.write_text(yaml.safe_dump(doc))


def deploy_images(doc, env, acr="acrx.azurecr.io"):
    doc["environments"][env]["images"] = {
        "frontend": f"{acr}/{doc['client']}/{doc['id']}-frontend@{DIGEST}",
        "backend": f"{acr}/{doc['client']}/{doc['id']}-backend@{DIGEST}",
    }


def render(root):
    return rp.render(rp.load(root), root)


def params(res, fname):
    return {k: v["value"] for k, v in res.files[fname]["parameters"].items()}


def test_example_registry_renders_stacks_in_order(repo):
    res = render(repo)
    assert res.errors == []
    assert [m["kind"] for m in res.manifest] == ["platform", "sandbox", "client", "backup"]
    backup = params(res, "backup.json")
    assert backup["adminIp"] == "192.0.2.17"
    assert any(s.endswith("vnet-demo-cpa/subnets/snet-cae-prod") for s in backup["allowedSubnetIds"])
    client = params(res, "client-demo-cpa.json")
    assert client["names"]["postgres"] == {"prod": "psql-demo-cpa-prod-05d1", "nonprod": "psql-demo-cpa-nonprod-05d1"}
    assert client["prodRetentionDays"] == 35


def test_undeployed_app_envs_are_skipped(repo):
    res = render(repo)
    assert not [m for m in res.manifest if m["kind"] == "app"]


def test_graduated_prod_app_params(repo):
    edit_yaml(app_path(repo, "demo-cpa", "intake-portal"), lambda d: deploy_images(d, "prod"))
    res = render(repo)
    assert res.errors == []
    v = params(res, "app-demo-cpa-intake-portal-prod.json")
    assert v["resourceGroupName"] == "rg-demo-cpa-intake-portal-prod"
    assert v["caeName"] == "cae-demo-cpa-prod"
    assert v["postgresServerName"] == "psql-demo-cpa-prod-05d1"
    assert v["databaseName"] == "intake_portal_prod"
    assert v["keyVaultName"] == "kv-demo-cpa-p-05d1"
    assert v["availabilityTest"] is True
    assert v["allowedCidrs"] == []
    entry = next(m for m in res.manifest if m["kind"] == "app")
    assert entry["subscription"] == "22222222-2222-2222-2222-222222222222"
    assert entry["meta"]["dbops_job"] == "caj-demo-cpa-dbops-prod"
    assert [m["kind"] for m in res.manifest][-1] == "backup"


def test_incubating_app_targets_sandbox(repo):
    edit_yaml(app_path(repo, "demo-tax", "ap-portal"), lambda d: deploy_images(d, "dev"))
    res = render(repo)
    v = params(res, "app-demo-tax-ap-portal-dev.json")
    assert v["resourceGroupName"] == "rg-sandbox-demo-tax-ap-portal"
    assert v["sharedResourceGroupName"] == "rg-sandbox-shared"
    assert v["databaseName"] == "demo_tax_ap_portal_dev"
    assert v["caeName"] == "cae-sandbox"
    assert v["availabilityTest"] is False
    entry = next(m for m in res.manifest if m["kind"] == "app")
    assert entry["subscription"] == "00000000-0000-0000-0000-000000000003"


def test_origins_rules_include_admin_ip_and_warn_without_test_ranges(repo):
    def enable(d):
        deploy_images(d, "prod")
        d["environments"]["prod"]["origins"] = {
            "enabled": True,
            "cidrs": [{"cidr": "203.0.113.0/24", "label": "Client VPN egress"}],
        }

    edit_yaml(app_path(repo, "demo-cpa", "intake-portal"), enable)
    res = render(repo)
    v = params(res, "app-demo-cpa-intake-portal-prod.json")
    assert v["allowedCidrs"] == [
        {"name": "client-vpn-egress", "cidr": "203.0.113.0/24"},
        {"name": "blufire-admin", "cidr": "192.0.2.17/32"},
    ]
    assert any("availabilityTestCidrs" in w for w in res.warnings)


@pytest.mark.parametrize(
    "target,mutate,message",
    [
        ("app", lambda d: d.update(client="nobody"), "has no file in registry/clients"),
        ("app", lambda d: d.update(stage="paused"), "stage"),
        ("app", lambda d: d["environments"]["dev"]["origins"].update(enabled=True), "origins is enabled with no cidrs"),
        ("app", lambda d: d["environments"]["dev"]["scale"].update(min=3, max=1), "scale.min is greater than max"),
        (
            "app",
            lambda d: d["environments"]["dev"].update(images={"frontend": f"a.io/x/y@{DIGEST}", "backend": None}),
            "needs both frontend and backend",
        ),
        ("client", lambda d: d.update(subscription_id=None), "needs subscription_id"),
        ("client", lambda d: d["postgres"].update(prod_high_availability=True), "General Purpose"),
    ],
)
def test_validation_errors(repo, target, mutate, message):
    path = (
        app_path(repo, "demo-cpa", "intake-portal")
        if target == "app"
        else repo / "registry/clients/demo-cpa.yaml"
    )
    edit_yaml(path, mutate)
    res = render(repo)
    assert any(message in e for e in res.errors), res.errors


def test_ha_allowed_on_general_purpose(repo):
    edit_yaml(
        repo / "registry/clients/demo-cpa.yaml",
        lambda d: d["postgres"].update(prod_sku="Standard_D2ds_v5", prod_high_availability=True),
    )
    res = render(repo)
    assert res.errors == []
    assert params(res, "client-demo-cpa.json")["prodHighAvailability"] is True


def test_ids_long_enough_to_break_azure_names_are_rejected(repo):
    # 20-character app ids keep ca-<a>-fe-<e> within Azure's 32-character limit; longer ids fail the schema.
    edit_yaml(repo / "registry/apps/demo-cpa/intake-portal.yaml", lambda d: d.update(id="intake-portal-for-all"))
    assert any("intake-portal-for-all" in e for e in render(repo).errors)
    longest = rp.app_env_names({"client": "abcdefghij", "id": "a" * 20, "stage": "graduated"}, "prod",
                               {"subscriptions": {}}, {"abcdefghij": {"subscription_id": "s"}})
    assert all(len(longest[k]) <= rp.NAME_LIMITS[kind] for k, kind in
               (("frontend", "container_app"), ("dbops_job", "job"), ("key_vault", "key_vault")))


def test_cli_writes_files_and_fails_on_errors(repo, tmp_path):
    out = tmp_path / "out"
    assert rp.main(["--root", str(repo), "--out", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    for entry in manifest:
        assert (out / entry["parameters"]).exists()
        assert len(entry["name"]) <= 64
    edit_yaml(app_path(repo, "demo-cpa", "intake-portal"), lambda d: d.update(client="nobody"))
    assert rp.main(["--root", str(repo), "--check"]) == 1


def test_digest_cron_is_utc():
    cron = rp._digest_cron({"digest": {"send_local_time": "07:00", "timezone": "America/New_York"}})
    minute, hour, *_ = cron.split()
    assert minute == "0" and hour in {"11", "12"}


def test_names_match_control_plane():
    src = ROOT / "control-plane/src/blufire_cp/naming.py"
    if not src.exists():
        pytest.skip("control plane naming module not present")
    spec = importlib.util.spec_from_file_location("cp_naming", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cp_naming"] = mod
    spec.loader.exec_module(mod)
    reg = rp.load(ROOT)
    for _, app in reg.apps:
        app = copy.deepcopy(app)
        for env in rp.ENVS:
            ours = rp.app_env_names(app, env, reg.platform, reg.clients)
            theirs = mod.app_env(app, env, reg.platform, reg.clients)
            for field in ("subscription", "resource_group", "shared_resource_group", "frontend", "backend",
                          "identity", "postgres_server", "database", "dbops_job", "app_insights"):
                assert ours[field] == getattr(theirs, field), (app["id"], env, field)


def test_rendered_params_match_templates(repo):
    """Every rendered parameter exists in its compiled template and every required one is provided."""
    import subprocess

    bicep = shutil.which("bicep")
    if not bicep:
        pytest.skip("bicep CLI not installed")
    edit_yaml(app_path(repo, "demo-cpa", "intake-portal"), lambda d: deploy_images(d, "prod"))
    res = render(repo)
    kinds = set()
    for m in res.manifest:
        arm = json.loads(subprocess.run([bicep, "build", str(ROOT / m["template"]), "--stdout"],
                                        capture_output=True, text=True, check=True).stdout)
        declared = arm["parameters"]
        given = set(res.files[m["parameters"]]["parameters"])
        assert given <= set(declared), (m["kind"], given - set(declared))
        required = {k for k, v in declared.items() if "defaultValue" not in v}
        assert required <= given, (m["kind"], required - given)
        kinds.add(m["kind"])
    assert kinds == {"platform", "sandbox", "client", "app", "backup"}
