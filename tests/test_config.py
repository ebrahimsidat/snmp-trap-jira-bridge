from __future__ import annotations

from pathlib import Path

import pytest

from trapbridge.config import ConfigError, load_config, parse_config
from trapbridge.models import Severity

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "example.yaml"


def minimal() -> dict[str, object]:
    return {
        "snmp": {"listeners": [{"name": "core", "port": 1162}], "communities": ["public"]},
        "rules": [{"name": "r", "trap_oid": ".1.3.6.1.6.3.1.1.5.3", "summary": "x", "severity": "Critical"}],
        "jira": {
            "base_url": "https://jira.example.test/",
            "service_desk_id": 1,
            "request_type_id": 10,
            "resolve_transition_id": 761,
            "auth_token": "t",
        },
    }


def test_example_config_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TRAPBRIDGE_COMMUNITY",
        "TRAPBRIDGE_V3_AUTH_KEY",
        "TRAPBRIDGE_V3_PRIV_KEY",
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "PAGERDUTY_ROUTING_KEY",
    ):
        monkeypatch.setenv(var, f"value-of-{var}")
    cfg = load_config(EXAMPLE)
    assert [listener.name for listener in cfg.snmp.listeners] == ["core-network", "cloud-platform"]
    assert cfg.jira.auth_token == "value-of-JIRA_API_TOKEN"
    assert cfg.pagerduty is not None


def test_minimal_config_normalises_values() -> None:
    cfg = parse_config(minimal())
    assert cfg.jira.base_url == "https://jira.example.test"
    assert cfg.jira.service_desk_id == "1"
    assert cfg.rules[0].trap_oid == "1.3.6.1.6.3.1.1.5.3"
    assert cfg.rules[0].severity is Severity.CRITICAL
    assert cfg.pagerduty is None


def test_missing_env_var_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_SECRET", raising=False)
    raw = minimal()
    raw["jira"]["auth_token"] = "${MISSING_SECRET}"  # type: ignore[index]
    with pytest.raises(ConfigError, match="MISSING_SECRET"):
        parse_config(raw)


def test_requires_community_or_v3_user() -> None:
    raw = minimal()
    raw["snmp"]["communities"] = []  # type: ignore[index]
    with pytest.raises(ConfigError, match="community"):
        parse_config(raw)


def test_duplicate_listener_names_rejected() -> None:
    raw = minimal()
    raw["snmp"]["listeners"] = [{"name": "a", "port": 1}, {"name": "a", "port": 2}]  # type: ignore[index]
    with pytest.raises(ConfigError, match="unique"):
        parse_config(raw)


def test_unknown_severity_rejected() -> None:
    raw = minimal()
    raw["rules"][0]["severity"] = "catastrophic"  # type: ignore[index]
    with pytest.raises(ConfigError, match="unknown severity"):
        parse_config(raw)


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/config.yaml")
