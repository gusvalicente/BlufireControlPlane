"""Runtime settings, read once from environment variables (see docs/runtime-config.md)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    dev_mode: bool = field(default_factory=lambda: _env("BLUFIRE_DEV_MODE") == "1")
    tenant_id: str = field(default_factory=lambda: _env("ENTRA_TENANT_ID"))
    api_audience: str = field(default_factory=lambda: _env("API_AUDIENCE"))
    azure_client_id: str = field(default_factory=lambda: _env("AZURE_CLIENT_ID"))
    ui_client_id: str = field(default_factory=lambda: _env("UI_CLIENT_ID"))
    step_up_acrs: str = field(default_factory=lambda: _env("STEP_UP_ACRS"))

    state_db_host: str = field(default_factory=lambda: _env("STATE_DB_HOST"))
    state_db_name: str = field(default_factory=lambda: _env("STATE_DB_NAME", "blufire"))
    state_db_user: str = field(default_factory=lambda: _env("STATE_DB_USER"))
    state_db_url: str = field(default_factory=lambda: _env("STATE_DB_URL"))  # override, used by tests and dev

    github_owner: str = field(default_factory=lambda: _env("GITHUB_OWNER"))
    github_repo: str = field(default_factory=lambda: _env("GITHUB_REPO"))
    github_app_id: str = field(default_factory=lambda: _env("GITHUB_APP_ID"))
    github_installation_id: str = field(default_factory=lambda: _env("GITHUB_APP_INSTALLATION_ID"))
    github_private_key: str = field(default_factory=lambda: _env("GITHUB_APP_PRIVATE_KEY"))

    heartbeat_token: str = field(default_factory=lambda: _env("HEARTBEAT_TOKEN"))
    log_analytics_workspace_id: str = field(default_factory=lambda: _env("LOG_ANALYTICS_WORKSPACE_ID"))
    backup_storage_account: str = field(default_factory=lambda: _env("BACKUP_STORAGE_ACCOUNT"))
    acs_endpoint: str = field(default_factory=lambda: _env("ACS_ENDPOINT"))
    digest_sender: str = field(default_factory=lambda: _env("DIGEST_SENDER"))

    platform_api_url: str = field(default_factory=lambda: _env("PLATFORM_API_URL", "http://localhost:8000"))
    api_scope: str = field(default_factory=lambda: _env("API_SCOPE"))
    mcp_audience: str = field(default_factory=lambda: _env("MCP_AUDIENCE"))
    mcp_resource_url: str = field(default_factory=lambda: _env("MCP_RESOURCE_URL", "http://localhost:8080/mcp"))
    mcp_allowed_oids: tuple[str, ...] = field(
        default_factory=lambda: tuple(o.strip() for o in _env("MCP_ALLOWED_OIDS").split(",") if o.strip())
    )

    step_up_max_age_s: int = 600


@lru_cache
def settings() -> Settings:
    return Settings()
