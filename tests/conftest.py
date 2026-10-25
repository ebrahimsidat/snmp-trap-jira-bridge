from __future__ import annotations

import pytest

from trapbridge.config import JiraConfig, RuleConfig
from trapbridge.models import Alert, Severity


@pytest.fixture
def jira_cfg() -> JiraConfig:
    return JiraConfig(
        base_url="https://jira.example.test",
        service_desk_id="1",
        request_type_id="10",
        resolve_transition_id="761",
        auth_email="bot@example.test",
        auth_token="token",
        severity_field="customfield_10050",
        severity_values={"critical": "Sev 1", "major": "Sev 2"},
        max_retries=2,
    )


@pytest.fixture
def rules() -> list[RuleConfig]:
    return [
        RuleConfig("link-down", "1.3.6.1.6.3.1.1.5.3", Severity.MAJOR, "Link down on {host}"),
        RuleConfig("link-up", "1.3.6.1.6.3.1.1.5.4", Severity.INFO, "Link up on {host}", clear=True),
        RuleConfig("vendor", "1.3.6.1.4.1.99999", Severity.MINOR, "Vendor event {1.3.6.1.4.1.99999.9}"),
        RuleConfig(
            "vendor-down",
            "1.3.6.1.4.1.99999.1.1",
            Severity.CRITICAL,
            "Node {host} down",
            host_varbind="1.3.6.1.4.1.99999.1.2.1",
        ),
    ]


def make_alert(
    host: str = "router-1",
    severity: Severity = Severity.MAJOR,
    clear: bool = False,
    source: str = "core",
) -> Alert:
    return Alert(
        source=source,
        host=host,
        rule="test",
        severity=severity,
        summary=f"test alert on {host}",
        is_clear=clear,
        details={"1.3.6.1.2.1.1.5.0": host},
        received_at=0.0,
    )
