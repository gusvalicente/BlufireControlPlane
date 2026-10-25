#!/usr/bin/env python3
"""Off-cloud heartbeat for the M2 Mac Mini. Runs every 5 minutes from launchd.

Checks every prod health endpoint and the platform heartbeat. If something is down, or the control plane's worker
has gone quiet, it alerts through a path that does not depend on Azure: an iMessage from this Mac (and optionally
a push webhook such as ntfy or Pushover). Standard library only, so it keeps working through Python upgrades.

Config: ~/.blufire/heartbeat.json
{
  "platform_heartbeat_url": "https://<domains.admin_ui>/api/heartbeat",
  "targets": {"intake-portal prod": "https://intake.example.com/api/health"},
  "imessage_to": "+18135550123",
  "webhook_url": "",
  "realert_minutes": 60
}
Heartbeat token: macOS Keychain item "blufire-heartbeat" (security add-generic-password -s blufire-heartbeat -a blufire -w).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home() / ".blufire"
STATE = HOME / "heartbeat-state.json"


def check(url: str, token: str | None = None, timeout: int = 15) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            if r.status != 200:
                return False, f"HTTP {r.status}"
            if token:  # platform heartbeat: the worker must be fresh too
                data = json.loads(body)
                return bool(data.get("ok")), f"worker last run {data.get('worker_last_run')}"
            return True, "ok"
    except (OSError, ValueError) as exc:  # URLError and timeouts are OSErrors; bad JSON is a ValueError
        return False, str(exc)[:200]


def evaluate(results: dict[str, tuple[bool, str]], state: dict, now: float, realert_s: int) -> tuple[list[str], dict]:
    """Return messages to send and the new state. Alert on change to down, re-alert while down, note recovery."""
    messages, new_state = [], {}
    for name, (ok, detail) in results.items():
        prev = state.get(name, {"ok": True, "alerted": 0})
        if ok:
            if not prev["ok"]:
                messages.append(f"RECOVERED: {name}")
            new_state[name] = {"ok": True, "alerted": 0}
        else:
            if prev["ok"] or now - prev.get("alerted", 0) >= realert_s:
                messages.append(f"DOWN: {name} ({detail})")
                new_state[name] = {"ok": False, "alerted": now}
            else:
                new_state[name] = prev
    return messages, new_state


def keychain(service: str) -> str:
    out = subprocess.run(["security", "find-generic-password", "-s", service, "-w"], capture_output=True, text=True, check=False)
    return out.stdout.strip()


def send(cfg: dict, text: str) -> None:
    text = f"BluFire heartbeat: {text}"
    if cfg.get("imessage_to"):
        script = (
            'on run argv\n tell application "Messages"\n'
            '  send (item 1 of argv) to participant (item 2 of argv) of (1st account whose service type = iMessage)\n'
            " end tell\nend run"
        )
        subprocess.run(["osascript", "-e", script, text, cfg["imessage_to"]], check=False)
    if cfg.get("webhook_url"):
        urllib.request.urlopen(urllib.request.Request(cfg["webhook_url"], data=text.encode()), timeout=15)
    subprocess.run(["osascript", "-e", f"display notification {json.dumps(text)} with title \"BluFire\""], check=False)


def main() -> int:
    cfg = json.loads((HOME / "heartbeat.json").read_text())
    results = {name: check(url) for name, url in cfg.get("targets", {}).items()}
    results["platform worker"] = check(cfg["platform_heartbeat_url"], keychain("blufire-heartbeat"))
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    messages, new_state = evaluate(results, state, time.time(), cfg.get("realert_minutes", 60) * 60)
    for m in messages:
        send(cfg, m)
    STATE.write_text(json.dumps(new_state))
    print(json.dumps({k: v[0] for k, v in results.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
