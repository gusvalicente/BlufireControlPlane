from blufire_cp.policy import classify, path_matches
from blufire_cp.registry import changed_paths, dump_yaml, load_yaml, merge_patch, to_plain

POLICY_FILE = "registry/apps/demo-cpa/intake-portal.yaml"


def test_merge_patch_keeps_comments_and_order():
    doc = load_yaml("# top\na: 1  # keep me\nb:\n  c: 2\n  d: 3\n")
    merge_patch(doc, {"b": {"c": 5, "d": None}, "e": [1]})
    out = dump_yaml(doc)
    assert "# keep me" in out and "# top" in out
    assert to_plain(doc) == {"a": 1, "b": {"c": 5}, "e": [1]}


def test_changed_paths_are_leaves():
    old = {"environments": {"prod": {"scale": {"min": 1, "max": 3}, "origins": {"enabled": False, "cidrs": []}}}}
    new = {"environments": {"prod": {"scale": {"min": 1, "max": 4}, "origins": {"enabled": True, "cidrs": []}}}}
    assert changed_paths(old, new) == ["environments.prod.origins.enabled", "environments.prod.scale.max"]


def test_path_matching():
    assert path_matches("environments.*.origins", "environments.dev.origins.cidrs")
    assert not path_matches("environments.*.origins", "environments.dev.scale.max")
    assert not path_matches("environments.prod", "environments")


def test_classify(ctx):
    policy = ctx.snapshot().policy
    low = classify(policy, POLICY_FILE, ["environments.dev.scale.max"])
    assert low.risk == "low" and low.matched_rules == []
    prod = classify(policy, POLICY_FILE, ["environments.prod.scale.max"])
    assert prod.risk == "approval" and "path:environments.prod" in prod.matched_rules
    origins = classify(policy, POLICY_FILE, ["environments.dev.origins.enabled"])
    assert origins.risk == "approval"
    agent = classify(policy, POLICY_FILE, ["alerts.latency_p95_ms"], actor_kind="agent")
    assert agent.matched_rules == ["actor:agent"]
    client = classify(policy, "registry/clients/demo-cpa.yaml", ["notes"])
    assert client.risk == "approval"
    alerts = classify(policy, "alerts/defaults.yaml", ["app_alerts.latency_p95_ms"])
    assert alerts.risk == "low"
    created = classify(policy, "registry/apps/x/y.yaml", ["id"], operation="create")
    assert "file_operation:create" in created.matched_rules
