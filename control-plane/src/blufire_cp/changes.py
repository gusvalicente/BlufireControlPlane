"""Change requests: UI or Claude edit registry YAML; low risk commits to main, the rest opens a PR to approve."""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass

from .auth import Principal
from .context import Context
from .gitstore import ConflictError
from .models import Change, _id, now
from .policy import classify
from .registry import (
    app_rule_errors,
    changed_paths,
    dump_yaml,
    kind_for_path,
    load_yaml,
    merge_patch,
    schema_errors,
    to_plain,
)


class ChangeError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class ChangeIn:
    title: str
    file: str
    patch: dict
    reason: str | None = None
    create: bool = False
    delete: bool = False


ALLOWED_PREFIXES = ("registry/clients/", "registry/apps/", "policies/", "alerts/", "platform.yaml")


def _validate(ctx: Context, path: str, doc: dict) -> None:
    kind = kind_for_path(path)
    if not kind:
        return
    errors = schema_errors(doc, ctx.schema(kind))
    if kind == "client" and not errors and path != f"registry/clients/{doc['id']}.yaml":
        errors.append(f"id: file must be registry/clients/{doc['id']}.yaml")
    if kind == "app" and not errors:
        snap = ctx.snapshot()
        errors = app_rule_errors(doc, snap.clients)
        clash = snap.app_files.get(doc.get("id"))
        if clash and clash != path:
            errors.append(f"id: app id '{doc['id']}' is already used by {clash}")
        if path != f"registry/apps/{doc.get('client')}/{doc.get('id')}.yaml":
            errors.append(f"id: file must be registry/apps/{doc.get('client')}/{doc.get('id')}.yaml")
    if errors:
        raise ChangeError(422, "invalid_registry", "; ".join(errors))


def propose(ctx: Context, req: ChangeIn, actor: Principal) -> Change:
    if not req.file.startswith(ALLOWED_PREFIXES) or ".." in req.file or not req.file.endswith(".yaml"):
        raise ChangeError(400, "bad_file", f"{req.file} is not an editable registry file")
    if actor.kind == "agent" and (req.create or req.delete):
        raise ChangeError(403, "forbidden", "the Agent role cannot create or delete registry files")

    if req.create:
        try:
            ctx.store.read_file(req.file)
            raise ChangeError(409, "exists", f"{req.file} already exists")
        except FileNotFoundError:
            pass
        old_text, sha, old_plain = "", None, {}
        new_doc = load_yaml(dump_yaml(req.patch))
    else:
        try:
            old_text, sha = ctx.store.read_file(req.file)
        except FileNotFoundError as exc:
            raise ChangeError(404, "not_found", f"{req.file} does not exist") from exc
        old_doc = load_yaml(old_text)
        old_plain = to_plain(old_doc)
        new_doc = None if req.delete else merge_patch(copy.deepcopy(old_doc), req.patch)

    new_text = None if new_doc is None else dump_yaml(new_doc)
    new_plain = {} if new_doc is None else to_plain(new_doc)
    if new_doc is not None:
        if not isinstance(new_plain, dict):
            raise ChangeError(422, "invalid_registry", "the file must be a YAML mapping")
        _validate(ctx, req.file, new_plain)
    if new_text == old_text:
        raise ChangeError(400, "no_change", "the patch does not change the file")

    operation = "create" if req.create else "delete" if req.delete else "update"
    result = classify(
        ctx.snapshot().policy, req.file, changed_paths(old_plain, new_plain), operation=operation, actor_kind=actor.kind
    )
    diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            (new_text or "").splitlines(keepends=True),
            f"a/{req.file}",
            f"b/{req.file}",
        )
    )
    change = Change(
        id=_id(),
        title=req.title,
        reason=req.reason,
        file=req.file,
        operation=operation,
        actor_kind=actor.kind,
        actor_oid=actor.oid,
        actor_name=actor.name,
        risk=result.risk,
        matched_rules=result.matched_rules,
        status="pending",
        diff=diff,
    )
    message = f"{req.title}\n\n{req.reason or ''}\n\nRequested-by: {actor.name} ({actor.kind})".strip()

    try:
        if result.risk == "low":
            change.commit_sha = ctx.store.commit_file(req.file, new_text, message, sha=sha)
            change.status, change.decided_at, change.decided_by = "applied", now(), "policy: low risk"
            ctx.invalidate()
        else:
            change.branch = f"change/{change.id}"
            ctx.store.create_branch(change.branch)
            change.files = [req.file]
            change.head_sha = ctx.store.commit_file(req.file, new_text, message, sha=sha, branch=change.branch)
            rules = "\n".join(f"- `{r}`" for r in result.matched_rules)
            pr = ctx.store.open_pr(change.branch, req.title, f"{req.reason or ''}\n\nNeeds approval because:\n{rules}")
            change.pr_number, change.pr_url = pr.number, pr.url
    except ConflictError as exc:
        raise ChangeError(409, "conflict", f"{req.file} changed since it was read; reload and try again") from exc

    with ctx.sessions() as s:
        s.add(change)
        s.commit()
    return change


def get(ctx: Context, change_id: str) -> Change:
    with ctx.sessions() as s:
        change = s.get(Change, change_id)
    if not change:
        raise ChangeError(404, "not_found", f"change {change_id} not found")
    return change


def _decide(ctx: Context, change_id: str) -> Change:
    change = get(ctx, change_id)
    if change.status != "pending":
        raise ChangeError(409, "not_pending", f"change {change_id} is {change.status}")
    return change


def approve(ctx: Context, change_id: str, admin: Principal) -> Change:
    change = _decide(ctx, change_id)
    try:
        # Merge exactly what Gus reviewed: the recorded head commit, touching only the recorded files.
        touched = set(ctx.store.pr_files(change.pr_number))
        if not touched <= set(change.files or [change.file]):
            raise ConflictError(f"PR {change.pr_number} now touches other files: {sorted(touched - set(change.files))}")
        change.commit_sha = ctx.store.merge_pr(change.pr_number, change.title, change.head_sha)
        change.status = "applied"
    except ConflictError as exc:
        change.status, change.decision_note = "failed", str(exc)
    change.decided_at, change.decided_by = now(), admin.name
    ctx.invalidate()
    with ctx.sessions() as s:
        s.merge(change)
        s.commit()
    if change.status == "failed":
        raise ChangeError(409, "merge_conflict", change.decision_note or "merge failed")
    return change


def reject(ctx: Context, change_id: str, admin: Principal, reason: str) -> Change:
    change = _decide(ctx, change_id)
    ctx.store.close_pr(change.pr_number, change.branch)
    change.status, change.decided_at, change.decided_by, change.decision_note = "rejected", now(), admin.name, reason
    with ctx.sessions() as s:
        s.merge(change)
        s.commit()
    return change


def as_dict(c: Change) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "reason": c.reason,
        "file": c.file,
        "actor": {"kind": c.actor_kind, "oid": c.actor_oid, "name": c.actor_name},
        "risk": c.risk,
        "matched_rules": c.matched_rules,
        "status": c.status,
        "diff": c.diff,
        "commit_sha": c.commit_sha,
        "pr_number": c.pr_number,
        "pr_url": c.pr_url,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
        "decided_by": c.decided_by,
    }


def _unified(path: str, old: str, new: str | None) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), (new or "").splitlines(keepends=True), f"a/{path}", f"b/{path}"
        )
    )


def propose_graduation(ctx: Context, app_id: str, subscription_id: str, actor: Principal) -> Change:
    """One PR that sets the client's subscription (if needed) and flips the app to graduated."""
    snap = ctx.snapshot(fresh=True)
    app = snap.app(app_id)
    if app["stage"] == "graduated":
        raise ChangeError(409, "already_graduated", f"{app_id} is already graduated")
    app_path, client_path = snap.app_files[app_id], f"registry/clients/{app['client']}.yaml"

    edits: list[tuple[str, str, str, str]] = []
    client_text, client_sha = ctx.store.read_file(client_path)
    client_doc = load_yaml(client_text)
    if client_doc.get("subscription_id") != subscription_id:
        client_doc["subscription_id"] = subscription_id
        edits.append((client_path, client_text, client_sha, dump_yaml(client_doc)))
    app_text, app_sha = ctx.store.read_file(app_path)
    app_doc = load_yaml(app_text)
    app_doc["stage"] = "graduated"
    new_app_text = dump_yaml(app_doc)
    edits.append((app_path, app_text, app_sha, new_app_text))

    clients = {**snap.clients, app["client"]: to_plain(client_doc)}
    errors = schema_errors(to_plain(app_doc), ctx.schema("app")) + app_rule_errors(to_plain(app_doc), clients)
    if errors:
        raise ChangeError(422, "invalid_registry", "; ".join(errors))

    title = f"Graduate {app['name']} to {app['client']}'s subscription"
    change = Change(
        id=_id(),
        title=title,
        reason="Runs the graduation workflow: client resources, redeploy, migrations, checks, sandbox cleanup.",
        file=app_path,
        operation="update",
        actor_kind=actor.kind,
        actor_oid=actor.oid,
        actor_name=actor.name,
        risk="approval",
        matched_rules=["operation:graduate"],
        status="pending",
        diff="".join(_unified(p, old, new) for p, old, _, new in edits),
    )
    change.branch = f"change/{change.id}"
    change.files = [p for p, _, _, _ in edits]
    try:
        ctx.store.create_branch(change.branch)
        for path, _, sha, new in edits:
            change.head_sha = ctx.store.commit_file(
                path, new, f"{title}\n\nRequested-by: {actor.name} ({actor.kind})", sha=sha, branch=change.branch
            )
        pr = ctx.store.open_pr(change.branch, title, change.reason)
    except ConflictError as exc:
        raise ChangeError(409, "conflict", str(exc)) from exc
    change.pr_number, change.pr_url = pr.number, pr.url
    with ctx.sessions() as s:
        s.add(change)
        s.commit()
    return change


def drift_patch(drift_resource: str, prop: str, env: str, live: str) -> dict:
    """Translate a drift item into the registry merge patch that would make git match live."""
    component = "frontend" if "-fe-" in drift_resource else "backend"
    if prop in ("scale.minReplicas", "scale.maxReplicas"):
        key = "min" if prop == "scale.minReplicas" else "max"
        return {"environments": {env: {"scale": {key: int(live)}}}}
    if prop == "image":
        return {"environments": {env: {"images": {component: live}}}}
    if prop.startswith("env."):
        return {"environments": {env: {"env_vars": {prop[4:]: None if live == "(missing)" else live}}}}
    if prop == "ingress.ipSecurityRestrictions":
        cidrs = [c.strip() for c in live.split(",") if c.strip()]
        return {
            "environments": {
                env: {
                    "origins": {
                        "enabled": bool(cidrs),
                        "cidrs": [{"cidr": c, "label": "Adopted from live"} for c in cidrs],
                    }
                }
            }
        }
    raise ChangeError(400, "unsupported", f"cannot adopt drift on {prop}")


def propose_drift_adoption(ctx: Context, drift_id: str, actor: Principal) -> Change:
    from .models import Drift

    with ctx.sessions() as s:
        d = s.get(Drift, drift_id)
    if not d or d.status != "open":
        raise ChangeError(404, "not_found", "open drift item not found")
    snap = ctx.snapshot()
    patch = drift_patch(d.resource, d.property, d.env, d.live)
    if d.property == "ingress.ipSecurityRestrictions":
        admin_ip = snap.platform.get("network", {}).get("admin_static_ip")
        cidrs = patch["environments"][d.env]["origins"]["cidrs"]
        patch["environments"][d.env]["origins"]["cidrs"] = [c for c in cidrs if c["cidr"] != admin_ip]
    change = propose(
        ctx,
        ChangeIn(
            title=f"Adopt live {d.property} for {d.app} {d.env}",
            file=snap.app_files[d.app],
            patch=patch,
            reason=f"Drift detected {d.detected_at:%Y-%m-%d}: git {d.desired}, live {d.live}",
        ),
        actor,
    )
    with ctx.sessions() as s:
        row = s.get(Drift, drift_id)
        row.status = "adopted" if change.status == "applied" else row.status
        s.commit()
    return change
