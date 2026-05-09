# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_tasks."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.todo_tasks import list_todo_tasks

TASKS_URL_TMPL = "https://graph.microsoft.com/v1.0/me/todo/lists/{}/tasks"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_tasks.get_token",
        lambda profile: token,
    )


def _task_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "task-1",
        "title": "Renew passport",
        "status": "notStarted",
        "importance": "normal",
        "isReminderOn": False,
        "categories": ["Personal"],
        "createdDateTime": "2026-05-01T10:00:00Z",
        "lastModifiedDateTime": "2026-05-01T10:00:00Z",
        "dueDateTime": {"dateTime": "2026-06-01T00:00:00", "timeZone": "UTC"},
        "@odata.etag": 'W/"task-etag"',
        "body": {"content": "Bring birth certificate", "contentType": "text"},
    }
    base.update(overrides)
    return base


@respx.mock
def test_returns_unified_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASKS_URL_TMPL.format("L1")).respond(json={"value": [_task_payload()]})
    result = list_todo_tasks("L1")
    assert len(result) == 1
    task = result[0]
    assert task["id"] == "task-1"
    assert task["title"] == "Renew passport"
    assert task["status"] == "not_completed"
    assert task["due_date"] == "2026-06-01T00:00:00"
    assert task["assignees"] == []
    assert task["source"] == "todo"
    assert task["etag"] == 'W/"task-etag"'
    assert task["list_id"] == "L1"
    assert task["body_preview"] == "Bring birth certificate"
    assert task["categories"] == ["Personal"]
    assert task["importance"] == "normal"
    assert task["is_reminder_on"] is False


@respx.mock
def test_completed_status_maps_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASKS_URL_TMPL.format("L1")).respond(
        json={"value": [_task_payload(status="completed")]}
    )
    result = list_todo_tasks("L1")
    assert result[0]["status"] == "completed"


@respx.mock
@pytest.mark.parametrize(
    "raw_status",
    ["notStarted", "inProgress", "waitingOnOthers", "deferred"],
)
def test_non_completed_statuses_map_to_not_completed(
    monkeypatch: pytest.MonkeyPatch, raw_status: str
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASKS_URL_TMPL.format("L1")).respond(
        json={"value": [_task_payload(status=raw_status)]}
    )
    result = list_todo_tasks("L1")
    assert result[0]["status"] == "not_completed"


@respx.mock
def test_status_filter_completed_adds_filter_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    route = respx.get(TASKS_URL_TMPL.format("L1")).respond(json={"value": []})
    list_todo_tasks("L1", status_filter="completed")
    url = (
        str(route.calls.last.request.url)
        .replace("%24", "$")
        .replace("%20", " ")
        .replace("+", " ")
        .replace("%27", "'")
    )
    assert "$filter=status eq 'completed'" in url


@respx.mock
def test_status_filter_not_completed_adds_negated_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    route = respx.get(TASKS_URL_TMPL.format("L1")).respond(json={"value": []})
    list_todo_tasks("L1", status_filter="not_completed")
    url = (
        str(route.calls.last.request.url)
        .replace("%24", "$")
        .replace("%20", " ")
        .replace("+", " ")
        .replace("%27", "'")
    )
    assert "$filter=status ne 'completed'" in url


@respx.mock
def test_status_filter_all_omits_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    route = respx.get(TASKS_URL_TMPL.format("L1")).respond(json={"value": []})
    list_todo_tasks("L1", status_filter="all")
    url = str(route.calls.last.request.url)
    assert "filter" not in url.lower()


def test_rejects_empty_list_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty list_id"):
        list_todo_tasks("")


def test_rejects_invalid_status_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="status_filter must be"):
        list_todo_tasks("L1", status_filter="urgent")


def test_rejects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        list_todo_tasks("L1", limit=0)


@respx.mock
def test_due_date_can_be_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    payload = _task_payload()
    del payload["dueDateTime"]
    respx.get(TASKS_URL_TMPL.format("L1")).respond(json={"value": [payload]})
    result = list_todo_tasks("L1")
    assert result[0]["due_date"] is None


@respx.mock
def test_categories_default_to_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    payload = _task_payload()
    payload["categories"] = "not-a-list"  # malformed
    respx.get(TASKS_URL_TMPL.format("L1")).respond(json={"value": [payload]})
    result = list_todo_tasks("L1")
    assert result[0]["categories"] == []


@respx.mock
def test_body_preview_truncates_at_200_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    long_body = "X" * 500
    payload = _task_payload(body={"content": long_body, "contentType": "text"})
    respx.get(TASKS_URL_TMPL.format("L1")).respond(json={"value": [payload]})
    result = list_todo_tasks("L1")
    assert len(result[0]["body_preview"]) == 200


@respx.mock
def test_skips_non_dict_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASKS_URL_TMPL.format("L1")).respond(
        json={"value": [None, "garbage", _task_payload()]}
    )
    result = list_todo_tasks("L1")
    assert len(result) == 1


@respx.mock
def test_propagates_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASKS_URL_TMPL.format("L1")).respond(403, json={"error": "forbidden"})
    with pytest.raises(httpx.HTTPStatusError):
        list_todo_tasks("L1")
