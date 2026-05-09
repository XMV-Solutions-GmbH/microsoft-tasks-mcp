# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_list_get."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.todo_list_get import get_todo_list

LIST_URL_TMPL = "https://graph.microsoft.com/v1.0/me/todo/lists/{}"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_list_get.get_token",
        lambda profile: token,
    )


@respx.mock
def test_returns_envelope_for_known_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LIST_URL_TMPL.format("list-1")).respond(
        json={
            "id": "list-1",
            "displayName": "Shopping",
            "isOwner": True,
            "isShared": False,
            "wellknownListName": "none",
            "@odata.etag": 'W/"e1"',
        }
    )
    result = get_todo_list("list-1")
    assert result == {
        "id": "list-1",
        "display_name": "Shopping",
        "is_owner": True,
        "is_shared": False,
        "well_known_list_name": "none",
        "etag": 'W/"e1"',
    }


def test_rejects_empty_list_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty list_id"):
        get_todo_list("")


def test_rejects_whitespace_list_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty list_id"):
        get_todo_list("   ")


@respx.mock
def test_strips_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LIST_URL_TMPL.format("xyz")).respond(json={"id": "xyz", "displayName": "OK"})
    result = get_todo_list("  xyz  ")
    assert result["id"] == "xyz"


@respx.mock
def test_propagates_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LIST_URL_TMPL.format("missing")).respond(
        404, json={"error": {"code": "ItemNotFound"}}
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        get_todo_list("missing")
    assert exc_info.value.response.status_code == 404


@respx.mock
def test_carries_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch, token="AT-XYZ")
    route = respx.get(LIST_URL_TMPL.format("a")).respond(json={"id": "a", "displayName": "A"})
    get_todo_list("a")
    assert route.calls.last.request.headers["Authorization"] == "Bearer AT-XYZ"


@respx.mock
def test_default_isowner_when_field_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LIST_URL_TMPL.format("a")).respond(json={"id": "a", "displayName": "A"})
    result = get_todo_list("a")
    assert result["is_owner"] is True
    assert result["is_shared"] is False
    assert result["etag"] is None
