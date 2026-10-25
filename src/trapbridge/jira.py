"""Async client for Jira Service Management.

Resilience features:

* Retries with exponential back-off on HTTP 429 and 5xx, honouring ``Retry-After``.
* **Self-healing field handling:** if Jira rejects a request because a field is
  not valid for the request type, that field is removed and the request is
  retried once, so a configuration drift degrades gracefully instead of
  dropping the alert.
* **Start-up validation:** the configured severity mapping is checked against
  the live request-type definition and mismatches are logged before the first
  alert arrives.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any

import httpx

from trapbridge.config import JiraConfig
from trapbridge.models import Alert

log = logging.getLogger(__name__)

_FIELD_IN_MESSAGE = re.compile(r"(customfield_\d+|summary|description|priority|labels|components)")


class JiraError(RuntimeError):
    """Raised when Jira cannot be reached or rejects a request permanently."""


def _auth_header(cfg: JiraConfig) -> str:
    if cfg.auth_email:
        token = base64.b64encode(f"{cfg.auth_email}:{cfg.auth_token}".encode()).decode()
        return f"Basic {token}"
    return f"Bearer {cfg.auth_token}"


def rejected_fields(payload: Any) -> list[str]:
    """Extract field IDs named in a Jira 400 response body."""
    fields: list[str] = []
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, dict):
            fields.extend(str(k) for k in errors)
        for key in ("errorMessage", "i18nErrorMessage"):
            message = payload.get(key)
            if isinstance(message, dict):
                message = message.get("i18nKey", "")
            if isinstance(message, str):
                fields.extend(_FIELD_IN_MESSAGE.findall(message))
        messages = payload.get("errorMessages")
        if isinstance(messages, list):
            for message in messages:
                fields.extend(_FIELD_IN_MESSAGE.findall(str(message)))
    return list(dict.fromkeys(fields))


class JiraClient:
    def __init__(self, cfg: JiraConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            base_url=cfg.base_url,
            timeout=cfg.timeout_seconds,
            transport=transport,
            headers={
                "Authorization": _auth_header(cfg),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(1, self._cfg.max_retries + 2):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("jira %s %s failed (attempt %d): %s", method, url, attempt, exc)
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = JiraError(f"HTTP {response.status_code}")
                    retry_after = response.headers.get("Retry-After", "")
                    if retry_after.isdigit():
                        delay = min(float(retry_after), 60.0)
                    log.warning(
                        "jira %s %s returned %d (attempt %d)", method, url, response.status_code, attempt
                    )
                else:
                    return response
            if attempt <= self._cfg.max_retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
        raise JiraError(f"{method} {url} failed after retries: {last_error}")

    def build_fields(self, alert: Alert) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "summary": f"[{alert.severity.value.upper()}] {alert.summary}"[:254],
            "description": self.describe(alert),
        }
        if self._cfg.severity_field:
            value = self._cfg.severity_values.get(alert.severity.value)
            if value:
                fields[self._cfg.severity_field] = {"value": value}
        fields.update(self._cfg.extra_fields)
        return fields

    @staticmethod
    def describe(alert: Alert, note: str = "") -> str:
        lines = []
        if note:
            lines += [note, ""]
        lines += [
            f"Host: {alert.host}",
            f"Source: {alert.source}",
            f"Rule: {alert.rule}",
            f"Severity: {alert.severity.value}",
            "",
            "Varbinds:",
        ]
        lines += [f"  {oid} = {value}" for oid, value in sorted(alert.details.items())]
        return "\n".join(lines)

    async def create_request(self, alert: Alert) -> str:
        """Create a service request and return its issue key."""
        fields = self.build_fields(alert)
        body: dict[str, Any] = {
            "serviceDeskId": self._cfg.service_desk_id,
            "requestTypeId": self._cfg.request_type_id,
            "requestFieldValues": fields,
        }
        response = await self._request("POST", "/rest/servicedeskapi/request", json=body)

        if response.status_code == 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            droppable = [f for f in rejected_fields(payload) if f in fields and f != "summary"]
            if droppable:
                log.warning("jira rejected fields %s; retrying without them", droppable)
                for name in droppable:
                    fields.pop(name, None)
                response = await self._request("POST", "/rest/servicedeskapi/request", json=body)

        if response.status_code not in (200, 201):
            raise JiraError(f"create request failed: HTTP {response.status_code} {response.text[:300]}")
        key = response.json().get("issueKey")
        if not key:
            raise JiraError("create request succeeded but no issueKey was returned")
        return str(key)

    async def add_comment(self, issue_key: str, text: str, public: bool = False) -> None:
        response = await self._request(
            "POST",
            f"/rest/servicedeskapi/request/{issue_key}/comment",
            json={"body": text, "public": public},
        )
        if response.status_code not in (200, 201):
            raise JiraError(f"comment on {issue_key} failed: HTTP {response.status_code}")

    async def resolve(self, issue_key: str, text: str) -> None:
        await self.add_comment(issue_key, text)
        response = await self._request(
            "POST",
            f"/rest/api/2/issue/{issue_key}/transitions",
            json={"transition": {"id": self._cfg.resolve_transition_id}},
        )
        if response.status_code not in (200, 204):
            raise JiraError(f"transition of {issue_key} failed: HTTP {response.status_code}")

    async def validate(self) -> list[str]:
        """Compare configured field values with the live request type; return warnings."""
        url = (
            f"/rest/servicedeskapi/servicedesk/{self._cfg.service_desk_id}"
            f"/requesttype/{self._cfg.request_type_id}/field"
        )
        response = await self._request("GET", url)
        if response.status_code != 200:
            return [f"could not read request type fields: HTTP {response.status_code}"]

        live = {f.get("fieldId"): f for f in response.json().get("requestTypeFields", [])}
        warnings: list[str] = []
        wanted = ["summary", "description", *self._cfg.extra_fields]
        if self._cfg.severity_field:
            wanted.append(self._cfg.severity_field)
        for field_id in wanted:
            if field_id not in live:
                warnings.append(f"field '{field_id}' is not on request type {self._cfg.request_type_id}")

        if self._cfg.severity_field in live:
            valid = {str(v.get("value")) for v in live[self._cfg.severity_field].get("validValues", [])}
            valid |= {str(v.get("label")) for v in live[self._cfg.severity_field].get("validValues", [])}
            for severity, value in self._cfg.severity_values.items():
                if valid and value not in valid:
                    warnings.append(
                        f"severity '{severity}' maps to '{value}', which is not a valid option "
                        f"for {self._cfg.severity_field}"
                    )
        for warning in warnings:
            log.warning("jira config: %s", warning)
        return warnings
