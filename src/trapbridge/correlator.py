"""Alert correlation: de-duplication, escalation and flap dampening.

Policy
------
* **One incident per node.** All alerts for the same ``source:host`` attach to a
  single open incident instead of opening a new ticket each time.
* **Repeats become comments,** rate-limited so a trap storm cannot flood a ticket.
  A severity escalation is always recorded, regardless of the rate limit.
* **Clears are held down.** A clear starts a timer; if the problem re-occurs
  before it expires (for example a node rebooting), the clear is cancelled and
  the ticket stays open. Only a clear that survives the hold-down resolves it.

The correlator is pure logic with an injectable clock, which keeps it fully
deterministic under test.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from trapbridge.config import CorrelationConfig
from trapbridge.models import Action, ActionType, Alert, Severity


@dataclass
class Incident:
    key: str
    opened_at: float
    severity: Severity
    last_comment_at: float
    alert_count: int = 1
    pending_clear_since: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Incident:
        return cls(
            key=str(data["key"]),
            opened_at=float(data["opened_at"]),
            severity=Severity(data["severity"]),
            last_comment_at=float(data["last_comment_at"]),
            alert_count=int(data.get("alert_count", 1)),
            pending_clear_since=(
                float(data["pending_clear_since"]) if data.get("pending_clear_since") is not None else None
            ),
        )


class Correlator:
    def __init__(self, config: CorrelationConfig) -> None:
        self._cfg = config
        self._incidents: dict[str, Incident] = {}
        self._last_alert: dict[str, Alert] = {}

    @property
    def open_incidents(self) -> dict[str, Incident]:
        return dict(self._incidents)

    def process(self, alert: Alert, now: float) -> list[Action]:
        key = alert.correlation_key
        incident = self._incidents.get(key)

        if alert.is_clear:
            if incident is not None and incident.pending_clear_since is None:
                incident.pending_clear_since = now
                self._last_alert[key] = alert
            return []

        self._last_alert[key] = alert

        if incident is None:
            self._incidents[key] = Incident(
                key=key, opened_at=now, severity=alert.severity, last_comment_at=now
            )
            return [Action(ActionType.CREATE, key, alert)]

        incident.alert_count += 1

        if incident.pending_clear_since is not None:
            incident.pending_clear_since = None
            incident.last_comment_at = now
            return [
                Action(
                    ActionType.COMMENT,
                    key,
                    alert,
                    note="Problem re-occurred during the clear hold-down period; resolution cancelled.",
                )
            ]

        if alert.severity.rank > incident.severity.rank:
            previous = incident.severity
            incident.severity = alert.severity
            incident.last_comment_at = now
            return [
                Action(
                    ActionType.COMMENT,
                    key,
                    alert,
                    note=f"Severity escalated from {previous.value} to {alert.severity.value}.",
                )
            ]

        if self._cfg.comment_on_repeat and (
            now - incident.last_comment_at >= self._cfg.min_comment_interval_seconds
        ):
            incident.last_comment_at = now
            return [
                Action(
                    ActionType.COMMENT,
                    key,
                    alert,
                    note=f"Repeat alert ({incident.alert_count} received for this incident).",
                )
            ]
        return []

    def poll(self, now: float) -> list[Action]:
        """Resolve incidents whose clear has survived the hold-down period."""
        actions: list[Action] = []
        for key, incident in list(self._incidents.items()):
            since = incident.pending_clear_since
            if since is not None and now - since >= self._cfg.clear_hold_down_seconds:
                del self._incidents[key]
                alert = self._last_alert.pop(key)
                actions.append(
                    Action(
                        ActionType.RESOLVE,
                        key,
                        alert,
                        note=f"Clear confirmed after {self._cfg.clear_hold_down_seconds:.0f}s hold-down.",
                    )
                )
        return actions

    def snapshot(self) -> dict[str, Any]:
        """Serialisable view of open incidents, used for restart persistence."""
        return {
            key: {"incident": inc.to_dict(), "alert": self._last_alert[key].to_dict()}
            for key, inc in self._incidents.items()
        }

    def restore(self, data: dict[str, Any]) -> None:
        self._incidents = {key: Incident.from_dict(v["incident"]) for key, v in data.items()}
        self._last_alert = {key: Alert.from_dict(v["alert"]) for key, v in data.items()}
