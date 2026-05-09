# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_task_get."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.todo_task_get import get_todo_task

URL_TMPL = "https://graph.microsoft.com/v1.0/me/todo/lists/{}/tasks/{}"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_task_get.get_token",
        lambda profile: token,
    )


@respx.mock
def test_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("L", "T")).respond(
        json={
            "id": "T",
            "title": "Pick up keys",
            "status": "completed",
            "@odata.etag": 'W/"e"',
            "categories": ["errand"],
            "importance": "high",
            "dueDateTime": {"dateTime": "2026-05-15T12:00:00", "timeZone": "UTC"},
        }
    )
    out = get_todo_task("L", "T")
    assert out["id"] == "T"
    assert out["title"] == "Pick up keys"
    assert out["status"] == "completed"
    assert out["due_date"] == "2026-05-15T12:00:00"
    assert out["list_id"] == "L"
    assert out["source"] == "todo"
    assert out["etag"] == 'W/"e"'
    assert out["categories"] == ["errand"]
    assert out["importance"] == "high"


def test_rejects_empty_list_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty list_id"):
        get_todo_task("", "T")


def test_rejects_empty_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty task_id"):
        get_todo_task("L", "")


@respx.mock
def test_propagates_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("L", "missing")).respond(404, json={"error": "ItemNotFound"})
    with pytest.raises(httpx.HTTPStatusError):
        get_todo_task("L", "missing")


@respx.mock
def test_strips_whitespace_in_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("L", "T")).respond(json={"id": "T", "title": "X"})
    out = get_todo_task("  L  ", "  T  ")
    assert out["id"] == "T"
    assert out["list_id"] == "L"


@respx.mock
def test_rejects_non_object_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("L", "T")).respond(json=["not", "an", "object"])
    with pytest.raises(ValueError, match="non-object response"):
        get_todo_task("L", "T")
