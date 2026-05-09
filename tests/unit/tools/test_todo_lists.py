# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_lists."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.todo_lists import list_todo_lists

LISTS_URL = "https://graph.microsoft.com/v1.0/me/todo/lists"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_lists.get_token",
        lambda profile: token,
    )


@respx.mock
def test_returns_lists_with_envelope_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LISTS_URL).respond(
        json={
            "value": [
                {
                    "id": "list-1",
                    "displayName": "Tasks",
                    "isOwner": True,
                    "isShared": False,
                    "wellknownListName": "defaultList",
                    "@odata.etag": 'W/"etag-1"',
                },
                {
                    "id": "list-2",
                    "displayName": "Customer follow-up",
                    "isOwner": True,
                    "isShared": False,
                    "wellknownListName": "none",
                    "@odata.etag": 'W/"etag-2"',
                },
            ]
        }
    )

    result = list_todo_lists()

    assert len(result) == 2
    assert result[0] == {
        "id": "list-1",
        "display_name": "Tasks",
        "is_owner": True,
        "is_shared": False,
        "well_known_list_name": "defaultList",
        "etag": 'W/"etag-1"',
    }
    assert result[1]["display_name"] == "Customer follow-up"


@respx.mock
def test_passes_limit_as_top_query_param(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    route = respx.get(LISTS_URL).respond(json={"value": []})
    list_todo_lists(limit=25)
    request = route.calls.last.request
    assert "%24top=25" in str(request.url) or "$top=25" in str(request.url)


@respx.mock
def test_default_limit_is_50(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    route = respx.get(LISTS_URL).respond(json={"value": []})
    list_todo_lists()
    request = route.calls.last.request
    assert "$top=50" in str(request.url).replace("%24", "$")


def test_rejects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        list_todo_lists(limit=0)


def test_rejects_negative_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        list_todo_lists(limit=-3)


@respx.mock
def test_carries_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch, token="AT-bearer")
    route = respx.get(LISTS_URL).respond(json={"value": []})
    list_todo_lists()
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer AT-bearer"


@respx.mock
def test_carries_user_agent_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    route = respx.get(LISTS_URL).respond(json={"value": []})
    list_todo_lists()
    headers = route.calls.last.request.headers
    assert headers["User-Agent"].startswith("mcp-server-microsoft-tasks/")


@respx.mock
def test_empty_value_field(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LISTS_URL).respond(json={"value": []})
    assert list_todo_lists() == []


@respx.mock
def test_value_missing_falls_back_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LISTS_URL).respond(json={})
    assert list_todo_lists() == []


@respx.mock
def test_skips_non_dict_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LISTS_URL).respond(json={"value": [None, "garbage", {"id": "ok"}]})
    result = list_todo_lists()
    assert len(result) == 1
    assert result[0]["id"] == "ok"


@respx.mock
def test_propagates_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LISTS_URL).respond(401, json={"error": "unauthorized"})
    with pytest.raises(httpx.HTTPStatusError):
        list_todo_lists()


@respx.mock
def test_uses_provided_http_client_without_closing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LISTS_URL).respond(json={"value": []})
    client = httpx.Client(timeout=10.0)
    try:
        list_todo_lists(http=client)
        # The client should still be usable after the call.
        assert client.is_closed is False
    finally:
        client.close()


@respx.mock
def test_missing_optional_fields_default_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(LISTS_URL).respond(json={"value": [{"id": "minimal", "displayName": "X"}]})
    out = list_todo_lists()
    assert out[0]["is_owner"] is True  # default True
    assert out[0]["is_shared"] is False
    assert out[0]["etag"] is None
    assert out[0]["well_known_list_name"] is None
