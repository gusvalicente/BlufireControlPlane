"""Registry documents: YAML round-trip (comments preserved), JSON merge patch, diffing and schema checks."""

from __future__ import annotations

import fnmatch
import io
import json
from dataclasses import dataclass
from typing import Any

import jsonschema
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

APP_GLOB = "registry/apps/*/*.yaml"
CLIENT_GLOB = "registry/clients/*.yaml"
ENVS = ("dev", "cert", "prod")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    return y


def load_yaml(text: str) -> Any:
    return _yaml().load(text) if text.strip() else CommentedMap()


def dump_yaml(doc: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def to_plain(doc: Any) -> Any:
    """Convert ruamel structures to plain JSON types."""
    return json.loads(json.dumps(doc, default=str))


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386 JSON merge patch, applied in place on ruamel maps so comments and key order survive."""
    if not isinstance(patch, dict):
        return patch
    if not isinstance(target, dict):
        target = CommentedMap()
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict):
            target[key] = merge_patch(target.get(key), value)
        else:
            target[key] = value
    return target


def changed_paths(old: Any, new: Any, prefix: str = "") -> list[str]:
    """Dotted paths of every leaf that differs. Lists are compared as whole values."""
    if isinstance(old, dict) and isinstance(new, dict):
        paths: list[str] = []
        for key in sorted(set(old) | set(new), key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in old:
                paths.extend(_leaves(new[key], child))
            elif key not in new:
                paths.extend(_leaves(old[key], child))
            else:
                paths.extend(changed_paths(old[key], new[key], child))
        return paths
    return [] if old == new else [prefix]


def _leaves(value: Any, prefix: str) -> list[str]:
    if isinstance(value, dict) and value:
        out: list[str] = []
        for key, child in value.items():
            out.extend(_leaves(child, f"{prefix}.{key}"))
        return out
    return [prefix]


def kind_for_path(path: str) -> str | None:
    if fnmatch.fnmatch(path, APP_GLOB):
        return "app"
    if fnmatch.fnmatch(path, CLIENT_GLOB):
        return "client"
    return None


def schema_errors(doc: Any, schema: dict) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{where}: {err.message}")
    return errors


def app_rule_errors(app: dict, clients: dict[str, dict]) -> list[str]:
    """Cross-document rules the JSON Schema cannot express."""
    errors = []
    client = clients.get(app.get("client", ""))
    if client is None:
        errors.append(f"client: unknown client '{app.get('client')}'")
    elif app.get("stage") == "graduated" and not client.get("subscription_id"):
        errors.append("stage: a graduated app needs its client's subscription_id set")
    for env, cfg in (app.get("environments") or {}).items():
        origins = cfg.get("origins") or {}
        if origins.get("enabled") and not origins.get("cidrs"):
            errors.append(f"environments.{env}.origins: enabled with no client networks would block the client")
        scale = cfg.get("scale") or {}
        if scale and scale.get("min", 0) > scale.get("max", 0):
            errors.append(f"environments.{env}.scale: min is greater than max")
    return errors


@dataclass
class Snapshot:
    """The registry as read from one commit of the platform repo."""

    platform: dict
    clients: dict[str, dict]
    apps: dict[str, dict]
    app_files: dict[str, str]  # app id -> repo path
    policy: dict
    alert_defaults: dict

    def app(self, app_id: str) -> dict:
        try:
            return self.apps[app_id]
        except KeyError as exc:
            raise KeyError(f"unknown app '{app_id}'") from exc
