from __future__ import annotations

from trapbridge.config import RuleConfig
from trapbridge.mapper import TrapMapper, render
from trapbridge.models import Severity, Trap


def trap(oid: str, varbinds: dict[str, str] | None = None) -> Trap:
    return Trap(listener="core", sender="10.0.0.5", trap_oid=oid, varbinds=varbinds or {}, received_at=1.0)


def test_render_fills_known_and_marks_unknown() -> None:
    assert (
        render("{host} {1.3.6.1.2.1.1.5.0} {nope}", {"host": "r1", "1.3.6.1.2.1.1.5.0": "sys"}) == "r1 sys ?"
    )


def test_exact_match(rules: list[RuleConfig]) -> None:
    alert = TrapMapper(rules).map(trap("1.3.6.1.6.3.1.1.5.3"))
    assert alert is not None
    assert alert.rule == "link-down"
    assert alert.host == "10.0.0.5"
    assert alert.summary == "Link down on 10.0.0.5"
    assert not alert.is_clear


def test_longest_prefix_wins(rules: list[RuleConfig]) -> None:
    mapper = TrapMapper(rules)
    assert mapper.match("1.3.6.1.4.1.99999.1.1").name == "vendor-down"  # type: ignore[union-attr]
    assert mapper.match("1.3.6.1.4.1.99999.7").name == "vendor"  # type: ignore[union-attr]


def test_prefix_requires_oid_boundary(rules: list[RuleConfig]) -> None:
    assert TrapMapper(rules).match("1.3.6.1.4.1.999991") is None


def test_host_from_varbind(rules: list[RuleConfig]) -> None:
    alert = TrapMapper(rules).map(trap("1.3.6.1.4.1.99999.1.1", {"1.3.6.1.4.1.99999.1.2.1": " node-7 "}))
    assert alert is not None
    assert alert.host == "node-7"
    assert alert.severity is Severity.CRITICAL
    assert alert.correlation_key == "core:node-7"


def test_host_falls_back_to_sender_when_varbind_missing(rules: list[RuleConfig]) -> None:
    alert = TrapMapper(rules).map(trap("1.3.6.1.4.1.99999.1.1"))
    assert alert is not None
    assert alert.host == "10.0.0.5"


def test_unmatched_trap_is_ignored(rules: list[RuleConfig]) -> None:
    assert TrapMapper(rules).map(trap("1.3.6.1.4.1.1.1")) is None


def test_clear_rule(rules: list[RuleConfig]) -> None:
    alert = TrapMapper(rules).map(trap(".1.3.6.1.6.3.1.1.5.4"))
    assert alert is not None
    assert alert.is_clear
