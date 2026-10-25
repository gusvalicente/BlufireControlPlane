"""Send logs and traces to Application Insights when a connection string is present."""

from __future__ import annotations

import logging
import os


def setup(service: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry import configure_azure_monitor

        os.environ.setdefault("OTEL_SERVICE_NAME", service)
        configure_azure_monitor(logger_name="blufire")


def event(name: str, **dims: str) -> None:
    """A named trace line the alert rules query (AppTraces where Message == name)."""
    logging.getLogger("blufire.events").warning(name, extra={k: str(v) for k, v in dims.items()})
