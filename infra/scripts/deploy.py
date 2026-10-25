#!/usr/bin/env python3
"""Deploy (or what-if) the rendered parameter files in manifest order.

    python infra/scripts/deploy.py whatif                         # everything
    python infra/scripts/deploy.py apply --changed-since <git-ref> # only deployments whose params changed
    python infra/scripts/deploy.py apply --only platform --set deployApps=false
    python infra/scripts/deploy.py apply --app intake-portal --env prod   # re-apply one app-env from git

Prod image changes get a pre-promotion dump (db-ops job) first, a revision health check after, and an automatic
redeploy of the previous parameters if the new revision is not healthy.
Requires: az CLI logged in, python deps from tools/ (pyyaml, jsonschema), git.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / "tools/render_params.py"
DRY_RUN = False


def run(cmd: list[str], check: bool = True, capture: bool = True) -> str:
    print("+ " + " ".join(cmd), flush=True)
    if DRY_RUN:
        return ""
    proc = subprocess.run(cmd, text=True, capture_output=capture, check=False)
    if check and proc.returncode != 0:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd[:4])}")
    return (proc.stdout or "").strip()


def az_json(cmd: list[str]):
    out = run(["az", *cmd, "-o", "json"])
    return json.loads(out) if out else None


def render(root: Path, out: Path) -> list[dict]:
    subprocess.run([sys.executable, str(RENDER), "--root", str(root), "--out", str(out)], check=True)
    return json.loads((out / "manifest.json").read_text())


def render_at(ref: str, workdir: Path) -> tuple[Path, list[dict]] | None:
    """Render the registry as it was at a git ref. None if the ref does not exist (first push)."""
    if not ref or set(ref) == {"0"}:
        return None
    if subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{ref}^{{commit}}"], check=False).returncode != 0:
        return None
    tree = workdir / "old-tree"
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(tree), ref], check=True,
                   capture_output=True)
    out = workdir / "old-params"
    try:
        manifest = render(tree, out)
    except subprocess.CalledProcessError:
        manifest = []
    finally:
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)], check=False)
    return out, manifest


def infra_changed(ref: str) -> bool:
    proc = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", ref, "HEAD", "--", "infra/"],
                          text=True, capture_output=True, check=False)
    return proc.returncode != 0 or bool(proc.stdout.strip())


def load_params(path: Path) -> dict:
    return {k: v["value"] for k, v in json.loads(path.read_text())["parameters"].items()}


def select(manifest: list[dict], only: list[str], app: str | None, env: str | None) -> list[dict]:
    if app:
        client, _, app_id = app.rpartition("/")
        chosen = [m for m in manifest if m["kind"] == "app" and m["meta"]["app"] == app_id
                  and (not client or m["meta"]["client"] == client) and (not env or m["meta"]["env"] == env)]
        if len({m["meta"]["client"] for m in chosen}) > 1:
            raise SystemExit(f"app '{app_id}' exists for several clients; pass client/app")
        if not chosen:
            raise SystemExit(f"no rendered deployment for app {app} env {env or '*'} (are its images set?)")
        return chosen
    if not only:
        return manifest
    picked = []
    for m in manifest:
        tags = {m["kind"]}
        if m["kind"] == "client":
            tags.add(f"client:{m['meta']['client']}")
        if m["kind"] == "app":
            meta = m["meta"]
            tags |= {f"app:{meta['client']}/{meta['app']}", f"app:{meta['client']}/{meta['app']}/{meta['env']}"}
        if tags & set(only):
            picked.append(m)
    return picked


def existing_subnets(ids: list[str]) -> list[str]:
    keep = []
    for sid in ids:
        if DRY_RUN or subprocess.run(["az", "network", "vnet", "subnet", "show", "--ids", sid, "-o", "none"],
                                     capture_output=True, check=False).returncode == 0:
            keep.append(sid)
        else:
            print(f"  skipping subnet not deployed yet: {sid}")
    return keep


def deployment_cmd(mode: str, m: dict, params_file: Path, overrides: list[str]) -> list[str]:
    verb = "what-if" if mode == "whatif" else "create"
    cmd = ["az", "deployment", "sub", verb, "--name", m["name"], "--location", m["location"],
           "--subscription", m["subscription"], "--template-file", str(ROOT / m["template"]),
           "--parameters", f"@{params_file}"]
    for o in overrides:
        cmd += ["--parameters", o]
    if mode == "apply":
        cmd += ["--only-show-errors", "-o", "none"]
    return cmd


def wait_job(job: str, rg: str, sub: str, execution: str, timeout_s: int = 3600) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = run(["az", "containerapp", "job", "execution", "show", "--name", job, "--resource-group", rg,
                      "--subscription", sub, "--job-execution-name", execution, "--query", "properties.status",
                      "-o", "tsv"])
        if DRY_RUN or status in {"Succeeded", "Failed", "Stopped", "Degraded"}:
            return status or "Succeeded"
        time.sleep(20)
    return "Timeout"


def start_dbops(sub: str, rg: str, job: str, args: list[str]) -> str:
    """Start a db-ops execution with new args. The start API replaces the container definition, so the job's
    current container (image, env, resources) is copied and only args change."""
    base = (f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
            f"/providers/Microsoft.App/jobs/{job}")
    current = az_json(["rest", "--method", "GET", "--uri", f"{base}?api-version=2024-03-01"]) or {}
    container = dict((current.get("properties", {}).get("template", {}).get("containers") or [{}])[0])
    container["args"] = args
    body = json.dumps({"containers": [container]})
    started = az_json(["rest", "--method", "POST", "--uri", f"{base}/start?api-version=2024-03-01",
                       "--headers", "Content-Type=application/json", "--body", body]) or {}
    return started.get("name", "dry-run")


def pre_promotion_dump(m: dict) -> None:
    meta = m["meta"]
    job, rg, sub = meta["dbops_job"], meta["shared_resource_group"], m["subscription"]
    execution = start_dbops(sub, rg, job, ["dump", "--app", meta["app"], "--env", meta["env"],
                                           "--database", meta["database"], "--layer", "pre_promotion"])
    status = wait_job(job, rg, sub, execution)
    if status != "Succeeded":
        raise SystemExit(f"pre-promotion dump for {meta['client']}/{meta['app']} ended {status}; not deploying")


def revision_healthy(app_name: str, rg: str, sub: str, timeout_s: int = 600) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        revs = az_json(["containerapp", "revision", "list", "--name", app_name, "--resource-group", rg,
                        "--subscription", sub, "--query",
                        "[?properties.active].{health:properties.healthState,prov:properties.provisioningState}"])
        if DRY_RUN:
            return True
        latest = (revs or [{}])[-1]
        if latest.get("health") == "Healthy" and latest.get("prov") == "Provisioned":
            return True
        if latest.get("health") == "Unhealthy" or latest.get("prov") == "Failed":
            return False
        time.sleep(15)
    return False


def tag_promotion(m: dict) -> None:
    meta = m["meta"]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    tag = f"prod/{meta['client']}/{meta['app']}/{meta.get('release') or 'release'}-{stamp}"
    run(["git", "-C", str(ROOT), "tag", tag])
    run(["git", "-C", str(ROOT), "push", "origin", tag])


REPORT_FILE: str | None = None


def summary(lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    print(text)
    for path in (os.environ.get("GITHUB_STEP_SUMMARY"), REPORT_FILE):
        if path:
            with open(path, "a") as f:
                f.write(text)


def main(argv: list[str] | None = None) -> int:
    global DRY_RUN, REPORT_FILE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["whatif", "apply"])
    ap.add_argument("--only", action="append", default=[],
                    help="platform | backup | sandbox | client | client:<c> | app | app:<c>/<a>[/<env>]")
    ap.add_argument("--app", help="<app> or <client>/<app>; with --env re-applies one app-env")
    ap.add_argument("--env", choices=["dev", "cert", "prod"])
    ap.add_argument("--changed-since", help="git ref; deploy only deployments whose parameters changed")
    ap.add_argument("--set", action="append", default=[], dest="overrides", help="parameter override key=value")
    ap.add_argument("--tag-promotions", action="store_true", help="git tag every prod image change")
    ap.add_argument("--dry-run", action="store_true", help="print commands without running them")
    ap.add_argument("--report", help="also write the markdown report to this file")
    args = ap.parse_args(argv)
    DRY_RUN = args.dry_run
    REPORT_FILE = args.report

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        new_dir = work / "params"
        manifest = select(render(ROOT, new_dir), args.only, args.app, args.env)
        old = render_at(args.changed_since, work) if args.changed_since else None
        old_dir, old_files = (old[0], {m["parameters"] for m in old[1]}) if old else (None, set())
        force_all = not args.changed_since or old is None or infra_changed(args.changed_since)

        report = [f"## Infrastructure {args.mode}", ""]
        for m in manifest:
            new_file = new_dir / m["parameters"]
            old_file = old_dir / m["parameters"] if old_dir and m["parameters"] in old_files else None
            changed = force_all or old_file is None or load_params(old_file) != load_params(new_file)
            if not changed:
                continue
            params_file = new_file
            if m["kind"] == "backup":
                values = json.loads(new_file.read_text())
                ids = values["parameters"]["allowedSubnetIds"]["value"]
                values["parameters"]["allowedSubnetIds"]["value"] = existing_subnets(ids)
                params_file = work / "backup-filtered.json"
                params_file.write_text(json.dumps(values))

            promoting = False
            if m["kind"] == "app" and m["meta"]["env"] == "prod" and old_file is not None:
                before, after = load_params(old_file), load_params(new_file)
                promoting = (before["frontendImage"], before["backendImage"]) != (after["frontendImage"],
                                                                                  after["backendImage"])

            if args.mode == "whatif":
                out = run(deployment_cmd("whatif", m, params_file, args.overrides))
                report += [f"### {m['name']}", "```", out[-60000:], "```", ""]
                continue

            if promoting:
                pre_promotion_dump(m)
            run(deployment_cmd("apply", m, params_file, args.overrides), capture=True)
            result = "applied"
            if promoting:
                meta = m["meta"]
                healthy = all(revision_healthy(name, meta["resource_group"], m["subscription"])
                              for name in (meta["backend"], meta["frontend"]))
                if not healthy:
                    run(deployment_cmd("apply", m, old_file, args.overrides))
                    summary(report + [f"- {m['name']}: new revision unhealthy, rolled back to previous images"])
                    return 1
                if args.tag_promotions:
                    tag_promotion(m)
                result = "promoted (pre-promotion dump taken, revisions healthy)"
            report.append(f"- {m['name']}: {result}")

        if len(report) == 2:
            report.append("No deployments changed.")
        summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
