"""blufire-worker <job>: run one scheduled job (Container Apps Job) and record the run for the heartbeat."""

from __future__ import annotations

import logging
import sys

from ..context import build_context
from ..models import WorkerRun, now
from ..telemetry import event, setup
from .jobs import JOBS

log = logging.getLogger("blufire.worker")


def run_job(ctx, name: str) -> int:
    job = JOBS[name]
    with ctx.sessions() as s:
        row = s.get(WorkerRun, name) or WorkerRun(job=name)
        row.last_started = now()
        s.merge(row)
        s.commit()
    try:
        detail, ok = job(ctx), True
    except Exception as exc:
        log.exception("job %s failed", name)
        detail, ok = str(exc)[:500], False
    with ctx.sessions() as s:
        row = s.get(WorkerRun, name)
        row.last_finished, row.ok, row.detail = now(), ok, detail
        s.commit()
    event("worker_heartbeat", app="platform", env="prod", detail=f"{name}: {'ok' if ok else 'failed'}")
    log.info("job %s finished ok=%s: %s", name, ok, detail)
    return 0 if ok else 1


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        print(f"usage: blufire-worker {{{'|'.join(JOBS)}}}", file=sys.stderr)
        raise SystemExit(2)
    setup(f"platform-worker-{sys.argv[1]}")
    raise SystemExit(run_job(build_context(), sys.argv[1]))
