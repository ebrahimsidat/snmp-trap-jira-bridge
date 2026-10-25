"""Full pipeline: trap -> mapper -> correlator -> dispatcher, plus persistence and CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_dispatcher import FakeJira
from trapbridge.app import Bridge, main
from trapbridge.config import parse_config
from trapbridge.dispatcher import Dispatcher
from trapbridge.models import Trap

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "example.yaml"


def config(tmp_path: Path) -> dict[str, object]:
    return {
        "state_file": str(tmp_path / "state.json"),
        "snmp": {"listeners": [{"name": "core", "port": 1162}], "communities": ["public"]},
        "rules": [
            {
                "name": "down",
                "trap_oid": "1.3.6.1.6.3.1.1.5.3",
                "summary": "Down {host}",
                "severity": "major",
            },
            {"name": "up", "trap_oid": "1.3.6.1.6.3.1.1.5.4", "summary": "Up {host}", "clear": True},
        ],
        "correlation": {"clear_hold_down_seconds": 0},
        "jira": {
            "base_url": "https://jira.example.test",
            "service_desk_id": "1",
            "request_type_id": "10",
            "resolve_transition_id": "761",
            "auth_token": "t",
        },
    }


def trap(oid: str) -> Trap:
    return Trap(listener="core", sender="10.1.1.1", trap_oid=oid, varbinds={})


async def test_pipeline_opens_and_persists(tmp_path: Path) -> None:
    bridge = Bridge(parse_config(config(tmp_path)))
    jira = FakeJira()
    bridge.dispatcher = Dispatcher(jira)

    await bridge.handle_trap(trap("1.3.6.1.6.3.1.1.5.3"))
    await bridge.handle_trap(trap("1.3.6.1.6.3.1.1.5.3"))
    assert jira.calls == [("create", "NOC-1")]

    restarted = Bridge(parse_config(config(tmp_path)))
    restarted.dispatcher = Dispatcher(FakeJira())
    restarted.restore()
    assert restarted.dispatcher.issues == {"core:10.1.1.1": "NOC-1"}
    assert "core:10.1.1.1" in restarted.correlator.open_incidents
    await bridge.close()
    await restarted.close()


async def test_pipeline_resolves_after_clear(tmp_path: Path) -> None:
    bridge = Bridge(parse_config(config(tmp_path)))
    jira = FakeJira()
    bridge.dispatcher = Dispatcher(jira)
    await bridge.handle_trap(trap("1.3.6.1.6.3.1.1.5.3"))
    await bridge.handle_trap(trap("1.3.6.1.6.3.1.1.5.4"))
    for action in bridge.correlator.poll(now=10**12):
        await bridge.dispatcher.handle(action)
    assert jira.calls[-1] == ("resolve", "NOC-1")
    await bridge.close()


def test_cli_check_succeeds(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for var in (
        "TRAPBRIDGE_COMMUNITY",
        "TRAPBRIDGE_V3_AUTH_KEY",
        "TRAPBRIDGE_V3_PRIV_KEY",
        "JIRA_EMAIL",
        "JIRA_API_TOKEN",
        "PAGERDUTY_ROUTING_KEY",
    ):
        monkeypatch.setenv(var, "x")
    assert main(["--config", str(EXAMPLE), "--check"]) == 0
    assert "configuration OK" in capsys.readouterr().out


def test_cli_reports_config_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", "/nonexistent.yaml"]) == 2
    assert "configuration error" in capsys.readouterr().err
