from __future__ import annotations

from conftest import make_alert
from trapbridge.config import CorrelationConfig
from trapbridge.correlator import Correlator
from trapbridge.models import ActionType, Severity

CFG = CorrelationConfig(clear_hold_down_seconds=120, comment_on_repeat=True, min_comment_interval_seconds=300)


def test_first_alert_creates_incident() -> None:
    actions = Correlator(CFG).process(make_alert(), now=0)
    assert [a.type for a in actions] == [ActionType.CREATE]


def test_repeats_are_deduplicated_and_rate_limited() -> None:
    c = Correlator(CFG)
    c.process(make_alert(), now=0)
    assert c.process(make_alert(), now=10) == []
    later = c.process(make_alert(), now=301)
    assert [a.type for a in later] == [ActionType.COMMENT]
    assert "3 received" in later[0].note


def test_different_hosts_get_separate_incidents() -> None:
    c = Correlator(CFG)
    c.process(make_alert("a"), now=0)
    actions = c.process(make_alert("b"), now=1)
    assert [a.type for a in actions] == [ActionType.CREATE]
    assert set(c.open_incidents) == {"core:a", "core:b"}


def test_escalation_always_comments() -> None:
    c = Correlator(CFG)
    c.process(make_alert(severity=Severity.MINOR), now=0)
    actions = c.process(make_alert(severity=Severity.CRITICAL), now=5)
    assert [a.type for a in actions] == [ActionType.COMMENT]
    assert "minor to critical" in actions[0].note


def test_clear_resolves_only_after_hold_down() -> None:
    c = Correlator(CFG)
    c.process(make_alert(), now=0)
    assert c.process(make_alert(clear=True), now=10) == []
    assert c.poll(now=100) == []
    resolved = c.poll(now=131)
    assert [a.type for a in resolved] == [ActionType.RESOLVE]
    assert c.open_incidents == {}


def test_flap_within_hold_down_cancels_resolution() -> None:
    c = Correlator(CFG)
    c.process(make_alert(), now=0)
    c.process(make_alert(clear=True), now=10)
    actions = c.process(make_alert(), now=60)
    assert [a.type for a in actions] == [ActionType.COMMENT]
    assert "resolution cancelled" in actions[0].note
    assert c.poll(now=500) == []
    assert "core:router-1" in c.open_incidents


def test_clear_without_incident_is_ignored() -> None:
    c = Correlator(CFG)
    assert c.process(make_alert(clear=True), now=0) == []
    assert c.poll(now=1000) == []


def test_snapshot_round_trip_preserves_pending_clear() -> None:
    c = Correlator(CFG)
    c.process(make_alert(), now=0)
    c.process(make_alert(clear=True), now=10)
    restored = Correlator(CFG)
    restored.restore(c.snapshot())
    resolved = restored.poll(now=200)
    assert [a.type for a in resolved] == [ActionType.RESOLVE]
    assert resolved[0].alert.host == "router-1"
