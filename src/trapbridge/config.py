"""Configuration loading and validation.

Secrets are never stored in the YAML file itself: any value written as
``${ENV_VAR}`` is resolved from the environment at load time, and a missing
variable is a hard error rather than a silent empty string.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from trapbridge.models import Severity

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """Raised when the configuration file is missing values or malformed."""


@dataclass(frozen=True)
class ListenerConfig:
    name: str
    host: str = "0.0.0.0"
    port: int = 162


@dataclass(frozen=True)
class V3UserConfig:
    username: str
    auth_key: str
    priv_key: str
    auth_protocol: str = "sha256"
    priv_protocol: str = "aes128"


@dataclass(frozen=True)
class SnmpConfig:
    listeners: tuple[ListenerConfig, ...]
    communities: tuple[str, ...] = ()
    v3_users: tuple[V3UserConfig, ...] = ()


@dataclass(frozen=True)
class RuleConfig:
    name: str
    trap_oid: str
    severity: Severity
    summary: str
    clear: bool = False
    host_varbind: str | None = None


@dataclass(frozen=True)
class CorrelationConfig:
    clear_hold_down_seconds: float = 120.0
    comment_on_repeat: bool = True
    min_comment_interval_seconds: float = 300.0


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    service_desk_id: str
    request_type_id: str
    resolve_transition_id: str
    auth_email: str | None = None
    auth_token: str = ""
    severity_field: str | None = None
    severity_values: dict[str, str] = field(default_factory=dict)
    extra_fields: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 15.0
    max_retries: int = 3


@dataclass(frozen=True)
class PagerDutyConfig:
    routing_key: str
    events_url: str = "https://events.pagerduty.com/v2/enqueue"


@dataclass(frozen=True)
class AppConfig:
    snmp: SnmpConfig
    rules: tuple[RuleConfig, ...]
    jira: JiraConfig
    correlation: CorrelationConfig = CorrelationConfig()
    pagerduty: PagerDutyConfig | None = None
    state_file: str | None = None
    log_level: str = "INFO"
    log_json: bool = False


def _expand_env(value: Any) -> Any:
    """Recursively replace ``${VAR}`` with environment values."""
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(f"environment variable {name} is not set")
            return os.environ[name]

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def _require(section: dict[str, Any], key: str, where: str) -> Any:
    if key not in section or section[key] in (None, ""):
        raise ConfigError(f"missing required setting '{where}.{key}'")
    return section[key]


def _parse_severity(value: Any, where: str) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError as exc:
        allowed = ", ".join(s.value for s in Severity)
        raise ConfigError(f"{where}: unknown severity '{value}' (allowed: {allowed})") from exc


def parse_config(raw: dict[str, Any]) -> AppConfig:
    """Build a validated :class:`AppConfig` from a plain dictionary."""
    data = _expand_env(raw)
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be a mapping")

    snmp_raw = data.get("snmp") or {}
    listeners_raw = _require(snmp_raw, "listeners", "snmp")
    listeners = tuple(
        ListenerConfig(
            name=str(_require(item, "name", "snmp.listeners[]")),
            host=str(item.get("host", "0.0.0.0")),
            port=int(item.get("port", 162)),
        )
        for item in listeners_raw
    )
    names = [listener.name for listener in listeners]
    if len(names) != len(set(names)):
        raise ConfigError("snmp.listeners: listener names must be unique")
    v3_users = tuple(
        V3UserConfig(
            username=str(_require(u, "username", "snmp.v3_users[]")),
            auth_key=str(_require(u, "auth_key", "snmp.v3_users[]")),
            priv_key=str(_require(u, "priv_key", "snmp.v3_users[]")),
            auth_protocol=str(u.get("auth_protocol", "sha256")).lower(),
            priv_protocol=str(u.get("priv_protocol", "aes128")).lower(),
        )
        for u in snmp_raw.get("v3_users", []) or []
    )
    communities = tuple(str(c) for c in snmp_raw.get("communities", []) or [])
    if not communities and not v3_users:
        raise ConfigError("snmp: configure at least one community or SNMPv3 user")
    snmp = SnmpConfig(listeners=listeners, communities=communities, v3_users=v3_users)

    rules_raw = _require(data, "rules", "root")
    rules = tuple(
        RuleConfig(
            name=str(_require(r, "name", "rules[]")),
            trap_oid=str(_require(r, "trap_oid", "rules[]")).lstrip("."),
            severity=_parse_severity(r.get("severity", "major"), f"rules[{r.get('name')}]"),
            summary=str(_require(r, "summary", "rules[]")),
            clear=bool(r.get("clear", False)),
            host_varbind=(str(r["host_varbind"]).lstrip(".") if r.get("host_varbind") else None),
        )
        for r in rules_raw
    )

    corr_raw = data.get("correlation") or {}
    correlation = CorrelationConfig(
        clear_hold_down_seconds=float(corr_raw.get("clear_hold_down_seconds", 120)),
        comment_on_repeat=bool(corr_raw.get("comment_on_repeat", True)),
        min_comment_interval_seconds=float(corr_raw.get("min_comment_interval_seconds", 300)),
    )

    jira_raw = _require(data, "jira", "root")
    jira = JiraConfig(
        base_url=str(_require(jira_raw, "base_url", "jira")).rstrip("/"),
        service_desk_id=str(_require(jira_raw, "service_desk_id", "jira")),
        request_type_id=str(_require(jira_raw, "request_type_id", "jira")),
        resolve_transition_id=str(_require(jira_raw, "resolve_transition_id", "jira")),
        auth_email=jira_raw.get("auth_email") or None,
        auth_token=str(_require(jira_raw, "auth_token", "jira")),
        severity_field=jira_raw.get("severity_field") or None,
        severity_values={str(k).lower(): str(v) for k, v in (jira_raw.get("severity_values") or {}).items()},
        extra_fields=dict(jira_raw.get("extra_fields") or {}),
        timeout_seconds=float(jira_raw.get("timeout_seconds", 15)),
        max_retries=int(jira_raw.get("max_retries", 3)),
    )

    pd_raw = data.get("pagerduty")
    pagerduty = None
    if pd_raw:
        pagerduty = PagerDutyConfig(
            routing_key=str(_require(pd_raw, "routing_key", "pagerduty")),
            events_url=str(pd_raw.get("events_url", PagerDutyConfig.events_url)),
        )

    return AppConfig(
        snmp=snmp,
        rules=rules,
        jira=jira,
        correlation=correlation,
        pagerduty=pagerduty,
        state_file=data.get("state_file") or None,
        log_level=str(data.get("log_level", "INFO")).upper(),
        log_json=bool(data.get("log_json", False)),
    )


def load_config(path: str | Path) -> AppConfig:
    """Load and validate a YAML configuration file."""
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"configuration file not found: {file}")
    with file.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return parse_config(raw)
