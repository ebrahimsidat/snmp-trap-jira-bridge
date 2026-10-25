"""Map raw traps to normalised alerts using configured rules."""

from __future__ import annotations

import logging
import re

from trapbridge.config import RuleConfig
from trapbridge.models import Alert, Trap

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def render(template: str, context: dict[str, str]) -> str:
    """Fill ``{name}`` placeholders; varbinds are addressed by OID, e.g. ``{1.3.6.1.2.1.1.5.0}``.

    Unknown placeholders render as ``?`` so a bad template never crashes the pipeline.
    """

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip().lstrip(".")
        return context.get(key, "?")

    return _PLACEHOLDER.sub(repl, template)


class TrapMapper:
    """Selects the most specific rule for a trap OID (longest prefix wins)."""

    def __init__(self, rules: tuple[RuleConfig, ...] | list[RuleConfig]) -> None:
        self._rules = sorted(rules, key=lambda r: len(r.trap_oid), reverse=True)

    def match(self, trap_oid: str) -> RuleConfig | None:
        oid = trap_oid.lstrip(".")
        for rule in self._rules:
            if oid == rule.trap_oid or oid.startswith(rule.trap_oid + "."):
                return rule
        return None

    def map(self, trap: Trap) -> Alert | None:
        rule = self.match(trap.trap_oid)
        if rule is None:
            log.info("no rule for trap %s from %s; ignored", trap.trap_oid, trap.sender)
            return None

        host = trap.sender
        if rule.host_varbind:
            host = trap.varbinds.get(rule.host_varbind, "").strip() or trap.sender

        context = {
            "host": host,
            "sender": trap.sender,
            "listener": trap.listener,
            "trap_oid": trap.trap_oid,
            "rule": rule.name,
            **trap.varbinds,
        }
        return Alert(
            source=trap.listener,
            host=host,
            rule=rule.name,
            severity=rule.severity,
            summary=render(rule.summary, context),
            is_clear=rule.clear,
            details=dict(trap.varbinds),
            received_at=trap.received_at,
        )
