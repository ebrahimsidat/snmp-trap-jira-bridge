"""PagerDuty Events API v2 client, used as the fail-over paging path."""

from __future__ import annotations

import logging

import httpx

from trapbridge.config import PagerDutyConfig
from trapbridge.models import Alert, Severity

log = logging.getLogger(__name__)

_PD_SEVERITY = {
    Severity.CRITICAL: "critical",
    Severity.MAJOR: "error",
    Severity.MINOR: "warning",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}


class PagerDutyClient:
    def __init__(self, cfg: PagerDutyConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(timeout=10.0, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(self, alert: Alert, action: str = "trigger", reason: str = "") -> None:
        """Send a trigger or resolve event; the dedup key keeps one PD incident per node."""
        body: dict[str, object] = {
            "routing_key": self._cfg.routing_key,
            "event_action": action,
            "dedup_key": alert.correlation_key,
        }
        if action == "trigger":
            body["payload"] = {
                "summary": f"{alert.summary} {reason}".strip()[:1024],
                "source": alert.host,
                "severity": _PD_SEVERITY[alert.severity],
                "component": alert.source,
                "custom_details": alert.details,
            }
        response = await self._client.post(self._cfg.events_url, json=body)
        if response.status_code != 202:
            raise RuntimeError(f"PagerDuty returned HTTP {response.status_code}: {response.text[:200]}")
        log.info("pagerduty %s sent for %s", action, alert.correlation_key)
