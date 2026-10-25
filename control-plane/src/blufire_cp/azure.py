"""Thin Azure REST client (ARM, Log Analytics, Resource Graph, Blob). Kept small so tests can fake it."""

from __future__ import annotations

import json
from typing import Any

import httpx

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
LA_SCOPE = "https://api.loganalytics.io/.default"
APP_API = "2024-03-01"


class Azure:
    def __init__(self, credential, storage_account: str = ""):
        self._cred = credential
        self._http = httpx.Client(timeout=60)
        self.storage_account = storage_account

    def _h(self, scope: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._cred.get_token(scope).token}"}

    def arm(self, method: str, path: str, api_version: str, body: dict | None = None) -> dict:
        r = self._http.request(
            method, f"{ARM}{path}", params={"api-version": api_version}, json=body, headers=self._h(ARM_SCOPE)
        )
        if r.status_code == 404:
            raise FileNotFoundError(path)
        r.raise_for_status()
        return r.json() if r.content else {}

    def log_query(self, workspace_id: str, kql: str, timespan: str = "P1D") -> list[dict[str, Any]]:
        r = self._http.post(
            f"https://api.loganalytics.io/v1/workspaces/{workspace_id}/query",
            json={"query": kql, "timespan": timespan},
            headers=self._h(LA_SCOPE),
        )
        r.raise_for_status()
        table = r.json()["tables"][0]
        cols = [c["name"] for c in table["columns"]]
        return [dict(zip(cols, row, strict=True)) for row in table["rows"]]

    def resource_graph(self, query: str, subscriptions: list[str]) -> list[dict[str, Any]]:
        body = {"subscriptions": subscriptions, "query": query, "options": {"resultFormat": "objectArray"}}
        return self.arm("POST", "/providers/Microsoft.ResourceGraph/resources", "2022-10-01", body).get("data", [])

    def container_app(self, sub: str, rg: str, name: str) -> dict:
        return self.arm(
            "GET", f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/containerApps/{name}", APP_API
        )

    def revisions(self, sub: str, rg: str, name: str) -> list[dict]:
        path = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/containerApps/{name}/revisions"
        return self.arm("GET", path, APP_API).get("value", [])

    def start_job(self, sub: str, rg: str, job: str, args: list[str]) -> str:
        path = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/jobs/{job}"
        container = self.arm("GET", path, APP_API)["properties"]["template"]["containers"][0]
        override = {"containers": [{**container, "args": args}]}
        return self.arm("POST", f"{path}/start", APP_API, override).get("name", "")

    def cost_month_to_date(self, sub: str) -> float:
        body = {
            "type": "ActualCost",
            "timeframe": "MonthToDate",
            "dataset": {"granularity": "None", "aggregation": {"total": {"name": "Cost", "function": "Sum"}}},
        }
        rows = self.arm("POST", f"/subscriptions/{sub}/providers/Microsoft.CostManagement/query", "2023-11-01", body)
        data = rows.get("properties", {}).get("rows", [])
        return float(data[0][0]) if data else 0.0

    def _container(self, name: str):
        from azure.storage.blob import BlobServiceClient

        svc = BlobServiceClient(f"https://{self.storage_account}.blob.core.windows.net", credential=self._cred)
        return svc.get_container_client(name)

    def list_json_blobs(self, container: str, prefix: str = "") -> list[tuple[str, dict]]:
        client = self._container(container)
        out = []
        for blob in client.list_blobs(name_starts_with=prefix):
            if blob.name.endswith(".json"):
                out.append((blob.name, json.loads(client.download_blob(blob.name).readall())))
        return out

    # ---------- Key Vault (metadata and rotation only; values are never returned to callers) ----------
    def list_secret_meta(self, vault: str) -> list[dict]:
        r = self._http.get(
            f"https://{vault}.vault.azure.net/secrets",
            params={"api-version": "7.4"},
            headers=self._h("https://vault.azure.net/.default"),
        )
        r.raise_for_status()
        return [{"name": v["id"].rsplit("/", 1)[-1], **v.get("attributes", {})} for v in r.json().get("value", [])]

    def set_secret(self, vault: str, name: str, value: str) -> None:
        r = self._http.put(
            f"https://{vault}.vault.azure.net/secrets/{name}",
            params={"api-version": "7.4"},
            json={"value": value},
            headers=self._h("https://vault.azure.net/.default"),
        )
        r.raise_for_status()

    def restart_latest_revision(self, sub: str, rg: str, name: str) -> None:
        app = self.container_app(sub, rg, name)
        rev = app["properties"]["latestRevisionName"]
        path = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/containerApps/{name}/revisions/{rev}/restart"
        self.arm("POST", path, APP_API)
