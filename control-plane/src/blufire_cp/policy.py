"""Decide whether a change commits directly or needs approval (policies/approvals.yaml)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from .registry import APP_GLOB


@dataclass(frozen=True)
class Classification:
    risk: str  # "low" | "approval"
    matched_rules: list[str]


def path_matches(rule: str, path: str) -> bool:
    """A rule matches when it is a segment-wise prefix of the changed path; '*' matches one segment."""
    rule_parts, path_parts = rule.split("."), path.split(".")
    if len(rule_parts) > len(path_parts):
        return False
    return all(r == "*" or r == p for r, p in zip(rule_parts, path_parts, strict=False))


def classify(
    policy: dict,
    file: str,
    paths: list[str],
    *,
    operation: str = "update",
    actor_kind: str = "admin",
) -> Classification:
    rules = policy.get("approval_required", {})
    matched: list[str] = []

    if actor_kind == "agent" and policy.get("agent_always_requires_approval", True):
        matched.append("actor:agent")
    if operation in rules.get("file_operations", []):
        matched.append(f"file_operation:{operation}")
    for pattern in rules.get("files", []):
        if fnmatch.fnmatch(file, pattern):
            matched.append(f"file:{pattern}")
    if fnmatch.fnmatch(file, APP_GLOB):
        for rule in rules.get("app_paths", []):
            if any(path_matches(rule, p) for p in paths):
                matched.append(f"path:{rule}")

    return Classification("approval" if matched else "low", matched)


def operation_needs_approval(policy: dict, operation: str) -> bool:
    return operation in policy.get("approval_required", {}).get("operations", [])


def approval_fields(policy: dict) -> list[str]:
    """App field rules, shown in the UI as lock badges."""
    return list(policy.get("approval_required", {}).get("app_paths", []))
