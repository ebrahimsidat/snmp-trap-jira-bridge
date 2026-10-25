"""Core data types shared across the pipeline."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class Severity(str, enum.Enum):
    """Normalised alert severity, independent of any vendor MIB."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {
    Severity.CRITICAL: 5,
    Severity.MAJOR: 4,
    Severity.MINOR: 3,
    Severity.WARNING: 2,
    Severity.INFO: 1,
}


@dataclass(frozen=True)
class Trap:
    """A raw SNMP notification as received on the wire."""

    listener: str
    sender: str
    trap_oid: str
    varbinds: dict[str, str]
    received_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Alert:
    """A trap after rule mapping: what happened, where, and how bad."""

    source: str
    host: str
    rule: str
    severity: Severity
    summary: str
    is_clear: bool
    details: dict[str, str]
    received_at: float

    @property
    def correlation_key(self) -> str:
        """Node-level key: one open incident per source + host."""
        return f"{self.source}:{self.host}"

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "host": self.host,
            "rule": self.rule,
            "severity": self.severity.value,
            "summary": self.summary,
            "is_clear": self.is_clear,
            "details": dict(self.details),
            "received_at": self.received_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alert:
        return cls(
            source=str(data["source"]),
            host=str(data["host"]),
            rule=str(data["rule"]),
            severity=Severity(data["severity"]),
            summary=str(data["summary"]),
            is_clear=bool(data["is_clear"]),
            details={str(k): str(v) for k, v in dict(data.get("details", {})).items()},
            received_at=float(data["received_at"]),
        )


class ActionType(str, enum.Enum):
    CREATE = "create"
    COMMENT = "comment"
    RESOLVE = "resolve"


@dataclass(frozen=True)
class Action:
    """A ticketing action decided by the correlator."""

    type: ActionType
    key: str
    alert: Alert
    note: str = ""
