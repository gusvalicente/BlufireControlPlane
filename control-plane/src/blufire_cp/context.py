"""Wiring shared by the API, worker and MCP server: git store, state DB, Azure client, registry snapshot."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from .db import make_sessions
from .gitstore import GitHubStore, GitStore, MemoryStore
from .registry import Snapshot, load_yaml, to_plain

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Context:
    store: GitStore
    sessions: sessionmaker[Session]
    azure: object | None = None
    ttl_s: float = 15.0
    _snap: tuple[float, Snapshot] | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def read_yaml(self, path: str) -> dict:
        text, _ = self.store.read_file(path)
        return to_plain(load_yaml(text))

    def schema(self, kind: str) -> dict:
        return json.loads(self.store.read_file(f"registry/schema/{kind}.schema.json")[0])

    def snapshot(self, fresh: bool = False) -> Snapshot:
        with self._lock:
            if not fresh and self._snap and time.monotonic() - self._snap[0] < self.ttl_s:
                return self._snap[1]
            clients = {}
            for path in self.store.list_files("registry/clients/"):
                if path.endswith(".yaml"):
                    doc = self.read_yaml(path)
                    clients[doc["id"]] = doc
            apps, files = {}, {}
            for path in self.store.list_files("registry/apps/"):
                if path.endswith(".yaml"):
                    doc = self.read_yaml(path)
                    apps[doc["id"]] = doc
                    files[doc["id"]] = path
            snap = Snapshot(
                platform=self.read_yaml("platform.yaml"),
                clients=clients,
                apps=apps,
                app_files=files,
                policy=self.read_yaml("policies/approvals.yaml"),
                alert_defaults=self.read_yaml("alerts/defaults.yaml"),
            )
            self._snap = (time.monotonic(), snap)
            return snap

    def invalidate(self) -> None:
        with self._lock:
            self._snap = None


def build_context() -> Context:
    from .config import settings

    s = settings()
    if s.dev_mode:
        return Context(store=MemoryStore.from_dir(REPO_ROOT), sessions=make_sessions())

    from azure.identity import DefaultAzureCredential

    from .azure import Azure

    credential = DefaultAzureCredential(managed_identity_client_id=s.azure_client_id or None)
    store = GitHubStore(s.github_owner, s.github_repo, s.github_app_id, s.github_installation_id, s.github_private_key)
    return Context(store=store, sessions=make_sessions(), azure=Azure(credential, s.backup_storage_account))
