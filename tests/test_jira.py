from __future__ import annotations

import json

import httpx
import pytest

from conftest import make_alert
from trapbridge import jira as jira_module
from trapbridge.config import JiraConfig
from trapbridge.jira import JiraClient, JiraError, rejected_fields


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(jira_module.asyncio, "sleep", instant)


def client(cfg: JiraConfig, handler: object) -> JiraClient:
    return JiraClient(cfg, transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_create_request_sends_mapped_fields(jira_cfg: JiraConfig) -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/servicedeskapi/request"
        assert request.headers["Authorization"].startswith("Basic ")
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"issueKey": "NOC-1"})

    jc = client(jira_cfg, handler)
    assert await jc.create_request(make_alert()) == "NOC-1"
    fields = seen[0]["requestFieldValues"]
    assert seen[0]["serviceDeskId"] == "1"
    assert fields["summary"].startswith("[MAJOR]")  # type: ignore[index]
    assert fields["customfield_10050"] == {"value": "Sev 2"}  # type: ignore[index]
    await jc.aclose()


async def test_self_heals_by_dropping_rejected_field(jira_cfg: JiraConfig) -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "customfield_10050" in body["requestFieldValues"]:
            return httpx.Response(400, json={"errors": {"customfield_10050": "Field is not valid"}})
        return httpx.Response(201, json={"issueKey": "NOC-2"})

    jc = client(jira_cfg, handler)
    assert await jc.create_request(make_alert()) == "NOC-2"
    assert len(bodies) == 2
    assert "customfield_10050" not in bodies[1]["requestFieldValues"]  # type: ignore[operator]
    await jc.aclose()


async def test_retries_server_errors_then_succeeds(jira_cfg: JiraConfig) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(201, json={"issueKey": "NOC-3"})

    jc = client(jira_cfg, handler)
    assert await jc.create_request(make_alert()) == "NOC-3"
    assert calls["n"] == 3
    await jc.aclose()


async def test_gives_up_after_max_retries(jira_cfg: JiraConfig) -> None:
    jc = client(jira_cfg, lambda request: httpx.Response(502))
    with pytest.raises(JiraError, match="after retries"):
        await jc.create_request(make_alert())
    await jc.aclose()


async def test_resolve_comments_then_transitions(jira_cfg: JiraConfig) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/transitions"):
            assert json.loads(request.content) == {"transition": {"id": "761"}}
            return httpx.Response(204)
        return httpx.Response(201, json={})

    jc = client(jira_cfg, handler)
    await jc.resolve("NOC-4", "cleared")
    assert paths == ["/rest/servicedeskapi/request/NOC-4/comment", "/rest/api/2/issue/NOC-4/transitions"]
    await jc.aclose()


async def test_validate_reports_mismatched_severity_values(jira_cfg: JiraConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "requestTypeFields": [
                    {"fieldId": "summary"},
                    {"fieldId": "description"},
                    {"fieldId": "customfield_10050", "validValues": [{"value": "Sev 1", "label": "Sev 1"}]},
                ]
            },
        )

    jc = client(jira_cfg, handler)
    warnings = await jc.validate()
    assert len(warnings) == 1
    assert "Sev 2" in warnings[0]
    await jc.aclose()


async def test_bearer_auth_without_email(jira_cfg: JiraConfig) -> None:
    from dataclasses import replace

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(201, json={"issueKey": "NOC-5"})

    jc = client(replace(jira_cfg, auth_email=None), handler)
    assert await jc.create_request(make_alert()) == "NOC-5"
    await jc.aclose()


def test_rejected_fields_parses_common_error_shapes() -> None:
    assert rejected_fields({"errors": {"customfield_1": "bad"}}) == ["customfield_1"]
    assert rejected_fields({"errorMessage": "Field customfield_22 is not valid"}) == ["customfield_22"]
    assert rejected_fields({"errorMessages": ["labels: invalid"]}) == ["labels"]
    assert rejected_fields("not json") == []
