from __future__ import annotations

from conftest import make_alert
from trapbridge.dispatcher import Dispatcher
from trapbridge.jira import JiraError
from trapbridge.models import Action, ActionType, Alert


class FakeJira:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.counter = 0

    async def create_request(self, alert: Alert) -> str:
        if self.fail:
            raise JiraError("down")
        self.counter += 1
        key = f"NOC-{self.counter}"
        self.calls.append(("create", key))
        return key

    async def add_comment(self, issue_key: str, text: str, public: bool = False) -> None:
        self.calls.append(("comment", issue_key))

    async def resolve(self, issue_key: str, text: str) -> None:
        self.calls.append(("resolve", issue_key))


class FakePager:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def send(self, alert: Alert, action: str = "trigger", reason: str = "") -> None:
        self.events.append((action, alert.correlation_key))


def act(kind: ActionType) -> Action:
    alert = make_alert()
    return Action(kind, alert.correlation_key, alert, note="n")


async def test_happy_path_create_comment_resolve() -> None:
    jira = FakeJira()
    d = Dispatcher(jira)
    await d.handle(act(ActionType.CREATE))
    await d.handle(act(ActionType.COMMENT))
    await d.handle(act(ActionType.RESOLVE))
    assert jira.calls == [("create", "NOC-1"), ("comment", "NOC-1"), ("resolve", "NOC-1")]
    assert d.issues == {}


async def test_jira_outage_pages_and_later_creates_ticket() -> None:
    jira, pager = FakeJira(fail=True), FakePager()
    d = Dispatcher(jira, pager)
    await d.handle(act(ActionType.CREATE))
    assert pager.events == [("trigger", "core:router-1")]
    assert d.issues == {}

    jira.fail = False
    await d.handle(act(ActionType.COMMENT))
    assert d.issues == {"core:router-1": "NOC-1"}

    await d.handle(act(ActionType.RESOLVE))
    assert pager.events[-1] == ("resolve", "core:router-1")
    assert d.paged == set()


async def test_snapshot_round_trip() -> None:
    d = Dispatcher(FakeJira())
    await d.handle(act(ActionType.CREATE))
    restored = Dispatcher(FakeJira())
    restored.restore(d.snapshot())
    assert restored.issues == {"core:router-1": "NOC-1"}
