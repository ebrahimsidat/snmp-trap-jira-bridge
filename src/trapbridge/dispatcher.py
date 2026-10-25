"""Execute correlator actions against Jira, with PagerDuty as fail-over."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from trapbridge.jira import JiraError
from trapbridge.models import Action, ActionType, Alert

log = logging.getLogger(__name__)


class Ticketing(Protocol):
    async def create_request(self, alert: Alert) -> str: ...
    async def add_comment(self, issue_key: str, text: str, public: bool = False) -> None: ...
    async def resolve(self, issue_key: str, text: str) -> None: ...


class Pager(Protocol):
    async def send(self, alert: Alert, action: str = "trigger", reason: str = "") -> None: ...


class Dispatcher:
    """Keeps the incident-to-ticket mapping and routes each action.

    If Jira is unreachable when an incident opens, the alert is paged out through
    PagerDuty so on-call is never left uninformed, and ticket creation is retried
    on the next update for that incident.
    """

    def __init__(self, jira: Ticketing, pager: Pager | None = None) -> None:
        self._jira = jira
        self._pager = pager
        self.issues: dict[str, str] = {}
        self.paged: set[str] = set()

    async def handle(self, action: Action) -> None:
        if action.type is ActionType.CREATE:
            await self._create(action)
        elif action.type is ActionType.COMMENT:
            await self._comment(action)
        elif action.type is ActionType.RESOLVE:
            await self._resolve(action)

    async def _create(self, action: Action) -> None:
        try:
            issue = await self._jira.create_request(action.alert)
        except JiraError as exc:
            log.error("jira create failed for %s: %s", action.key, exc)
            await self._page(action.alert, "trigger", "(Jira unavailable: ticket pending)")
            return
        self.issues[action.key] = issue
        log.info("opened %s for %s", issue, action.key)

    async def _comment(self, action: Action) -> None:
        issue = self.issues.get(action.key)
        if issue is None:
            await self._create(action)
            issue = self.issues.get(action.key)
            if issue is None:
                return
        try:
            await self._jira.add_comment(issue, f"{action.note}\n\n{action.alert.summary}".strip())
        except JiraError as exc:
            log.error("jira comment failed on %s: %s", issue, exc)

    async def _resolve(self, action: Action) -> None:
        issue = self.issues.pop(action.key, None)
        if issue is not None:
            try:
                await self._jira.resolve(issue, action.note)
                log.info("resolved %s for %s", issue, action.key)
            except JiraError as exc:
                log.error("jira resolve failed on %s: %s", issue, exc)
        if action.key in self.paged:
            await self._page(action.alert, "resolve")

    async def _page(self, alert: Alert, event: str, reason: str = "") -> None:
        if self._pager is None:
            if event == "trigger":
                log.critical("no pager configured; alert for %s was not delivered", alert.correlation_key)
            return
        try:
            await self._pager.send(alert, event, reason)
        except Exception as exc:  # noqa: BLE001 - paging must never crash the pipeline
            log.critical("pagerduty %s failed for %s: %s", event, alert.correlation_key, exc)
            return
        if event == "trigger":
            self.paged.add(alert.correlation_key)
        else:
            self.paged.discard(alert.correlation_key)

    def snapshot(self) -> dict[str, Any]:
        return {"issues": dict(self.issues), "paged": sorted(self.paged)}

    def restore(self, data: dict[str, Any]) -> None:
        self.issues = {str(k): str(v) for k, v in data.get("issues", {}).items()}
        self.paged = set(data.get("paged", []))
