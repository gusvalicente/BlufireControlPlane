"""Read and change the platform repo. GitHubStore talks to GitHub as a GitHub App; MemoryStore is for dev and tests."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx
import jwt

API = "https://api.github.com"


class ConflictError(Exception):
    """The file or PR changed underneath us (stale sha, merge conflict)."""


@dataclass
class PullRequest:
    number: int
    url: str
    branch: str
    state: str = "open"  # open | merged | closed


class GitStore(Protocol):
    def read_file(self, path: str, ref: str = "main") -> tuple[str, str]: ...
    def list_files(self, prefix: str, ref: str = "main") -> list[str]: ...
    def commit_file(
        self, path: str, text: str | None, message: str, *, sha: str | None, branch: str = "main"
    ) -> str: ...
    def create_branch(self, name: str, from_ref: str = "main") -> None: ...
    def open_pr(self, branch: str, title: str, body: str) -> PullRequest: ...
    def merge_pr(self, number: int, title: str, head_sha: str | None) -> str: ...
    def pr_files(self, number: int) -> list[str]: ...
    def close_pr(self, number: int, branch: str) -> None: ...


class GitHubStore:
    def __init__(self, owner: str, repo: str, app_id: str, installation_id: str, private_key: str):
        self.owner, self.repo = owner, repo
        self._app_id, self._installation_id, self._key = app_id, installation_id, private_key
        self._token: tuple[str, float] | None = None
        self._http = httpx.Client(base_url=API, timeout=20)

    def _auth(self) -> dict[str, str]:
        if not self._token or self._token[1] - 60 < time.time():
            now = int(time.time())
            app_jwt = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self._app_id}, self._key, algorithm="RS256")
            r = self._http.post(
                f"/app/installations/{self._installation_id}/access_tokens",
                headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
            )
            r.raise_for_status()
            self._token = (r.json()["token"], now + 3600)
        return {"Authorization": f"Bearer {self._token[0]}", "Accept": "application/vnd.github+json"}

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        r = self._http.request(method, url, headers=self._auth(), **kw)
        if r.status_code in (405, 409, 422) and method in ("PUT", "DELETE"):
            raise ConflictError(r.json().get("message", r.text))
        if r.status_code == 404:
            raise FileNotFoundError(url)
        r.raise_for_status()
        return r

    @property
    def _base(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"

    def read_file(self, path: str, ref: str = "main") -> tuple[str, str]:
        data = self._req("GET", f"{self._base}/contents/{path}", params={"ref": ref}).json()
        return base64.b64decode(data["content"]).decode(), data["sha"]

    def list_files(self, prefix: str, ref: str = "main") -> list[str]:
        tree = self._req("GET", f"{self._base}/git/trees/{ref}", params={"recursive": "1"}).json()
        return sorted(t["path"] for t in tree["tree"] if t["type"] == "blob" and t["path"].startswith(prefix))

    def commit_file(self, path: str, text: str | None, message: str, *, sha: str | None, branch: str = "main") -> str:
        if text is None:
            body = {"message": message, "sha": sha, "branch": branch}
            r = self._req("DELETE", f"{self._base}/contents/{path}", json=body)
        else:
            body = {"message": message, "content": base64.b64encode(text.encode()).decode(), "branch": branch}
            if sha:
                body["sha"] = sha
            r = self._req("PUT", f"{self._base}/contents/{path}", json=body)
        return r.json()["commit"]["sha"]

    def create_branch(self, name: str, from_ref: str = "main") -> None:
        base = self._req("GET", f"{self._base}/git/ref/heads/{from_ref}").json()["object"]["sha"]
        self._req("POST", f"{self._base}/git/refs", json={"ref": f"refs/heads/{name}", "sha": base})

    def open_pr(self, branch: str, title: str, body: str) -> PullRequest:
        data = self._req(
            "POST", f"{self._base}/pulls", json={"title": title, "head": branch, "base": "main", "body": body}
        )
        pr = data.json()
        return PullRequest(pr["number"], pr["html_url"], branch)

    def merge_pr(self, number: int, title: str, head_sha: str | None) -> str:
        body = {"merge_method": "squash", "commit_title": title}
        if head_sha:
            body["sha"] = head_sha  # GitHub refuses the merge if the branch moved since Gus reviewed it
        r = self._req("PUT", f"{self._base}/pulls/{number}/merge", json=body)
        return r.json()["sha"]

    def pr_files(self, number: int) -> list[str]:
        files: list[str] = []
        page = 1
        while True:
            batch = self._req("GET", f"{self._base}/pulls/{number}/files", params={"per_page": 100, "page": page}).json()
            files += [f["filename"] for f in batch] + [f["previous_filename"] for f in batch if f.get("previous_filename")]
            if len(batch) < 100:
                return files
            page += 1

    def close_pr(self, number: int, branch: str) -> None:
        self._req("PATCH", f"{self._base}/pulls/{number}", json={"state": "closed"})
        self._http.request("DELETE", f"{self._base}/git/refs/heads/{branch}", headers=self._auth())

    def dispatch_workflow(self, workflow: str, inputs: dict[str, str] | None = None) -> None:
        self._req(
            "POST",
            f"{self._base}/actions/workflows/{workflow}/dispatches",
            json={"ref": "main", "inputs": inputs or {}},
        )

    def dependabot_alerts(self, repo: str) -> list[dict]:
        """Open alerts, all pages. Raises on any error so callers never mistake a failure for zero alerts."""
        alerts: list[dict] = []
        url, params = f"/repos/{repo}/dependabot/alerts", {"state": "open", "per_page": 100}
        while url:
            r = self._http.get(url, params=params, headers=self._auth())
            r.raise_for_status()
            alerts += r.json()
            url, params = r.links.get("next", {}).get("url"), None
        return alerts


@dataclass
class MemoryStore:
    """In-memory repo with branches and PRs. `from_dir` seeds main from a checkout on disk."""

    branches: dict[str, dict[str, str]] = field(default_factory=lambda: {"main": {}})
    prs: dict[int, PullRequest] = field(default_factory=dict)
    bases: dict[str, dict[str, str]] = field(default_factory=dict)
    heads: dict[str, str] = field(default_factory=dict)
    commits: int = 0

    @classmethod
    def from_dir(cls, root: Path, prefixes: tuple[str, ...] = ("registry/", "policies/", "alerts/", "platform.yaml")):
        store = cls()
        for path in root.rglob("*"):
            rel = path.relative_to(root).as_posix()
            if path.is_file() and rel.startswith(prefixes):
                store.branches["main"][rel] = path.read_text()
        return store

    @staticmethod
    def _sha(text: str) -> str:
        import hashlib

        return hashlib.sha1(text.encode()).hexdigest()  # noqa: S324 - content id, not security

    def read_file(self, path: str, ref: str = "main") -> tuple[str, str]:
        files = self.branches[ref]
        if path not in files:
            raise FileNotFoundError(path)
        return files[path], self._sha(files[path])

    def list_files(self, prefix: str, ref: str = "main") -> list[str]:
        return sorted(p for p in self.branches[ref] if p.startswith(prefix))

    def commit_file(self, path: str, text: str | None, message: str, *, sha: str | None, branch: str = "main") -> str:
        files = self.branches[branch]
        current = files.get(path)
        if current is not None and sha != self._sha(current):
            raise ConflictError(f"{path} changed since it was read")
        if current is None and sha is not None:
            raise ConflictError(f"{path} no longer exists")
        if text is None:
            files.pop(path, None)
        else:
            files[path] = text
        self.commits += 1
        self.heads[branch] = f"c{self.commits:07d}"
        return self.heads[branch]

    def create_branch(self, name: str, from_ref: str = "main") -> None:
        self.branches[name] = dict(self.branches[from_ref])
        self.bases[name] = dict(self.branches[from_ref])

    def open_pr(self, branch: str, title: str, body: str) -> PullRequest:
        number = len(self.prs) + 1
        pr = PullRequest(number, f"https://github.local/pr/{number}", branch)
        self.prs[number] = pr
        return pr

    def pr_files(self, number: int) -> list[str]:
        pr = self.prs[number]
        head, base = self.branches[pr.branch], self.bases[pr.branch]
        return sorted(p for p in set(base) | set(head) if base.get(p) != head.get(p))

    def merge_pr(self, number: int, title: str, head_sha: str | None) -> str:
        pr = self.prs[number]
        if pr.state != "open":
            raise ConflictError(f"PR {number} is {pr.state}")
        if head_sha and self.heads.get(pr.branch) != head_sha:
            raise ConflictError(f"PR {number} head moved since it was reviewed")
        main, head, base = self.branches["main"], self.branches[pr.branch], self.bases[pr.branch]
        changed = {p for p in set(base) | set(head) if base.get(p) != head.get(p)}
        if any(main.get(p) != base.get(p) for p in changed):
            raise ConflictError(f"PR {number} conflicts with main")
        for p in changed:
            if p in head:
                main[p] = head[p]
            else:
                main.pop(p, None)
        pr.state = "merged"
        self.commits += 1
        return f"m{self.commits:07d}"

    def close_pr(self, number: int, branch: str) -> None:
        self.prs[number].state = "closed"
        self.branches.pop(branch, None)

    dispatched: list = field(default_factory=list)

    def dispatch_workflow(self, workflow: str, inputs: dict[str, str] | None = None) -> None:
        self.dispatched.append((workflow, inputs or {}))

    def dependabot_alerts(self, repo: str) -> list[dict]:
        return []
