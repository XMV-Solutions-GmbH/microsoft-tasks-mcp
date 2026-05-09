# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for tasks_search."""

from __future__ import annotations

import pytest
import respx

from microsoft_tasks_mcp.tools.tasks_search import search

GRAPH = "https://graph.microsoft.com/v1.0"
PLANNER_ME = f"{GRAPH}/me/planner/tasks"
TODO_LISTS = f"{GRAPH}/me/todo/lists"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.tasks_search.get_token",
        lambda profile: token,
    )


@respx.mock
def test_matches_title_substring(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={
            "value": [
                {"id": "t1", "title": "Renew passport", "status": "notStarted"},
                {"id": "t2", "title": "Buy milk", "status": "notStarted"},
            ]
        }
    )
    respx.get(PLANNER_ME).respond(json={"value": []})
    out = search("passport")
    assert [t["id"] for t in out] == ["t1"]


@respx.mock
def test_match_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": "t1", "title": "PASSPORT renewal"}]}
    )
    respx.get(PLANNER_ME).respond(json={"value": []})
    out = search("passport")
    assert [t["id"] for t in out] == ["t1"]


@respx.mock
def test_matches_body_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={
            "value": [
                {
                    "id": "t1",
                    "title": "Generic task",
                    "body": {"content": "Bring birth certificate"},
                }
            ]
        }
    )
    respx.get(PLANNER_ME).respond(json={"value": []})
    assert [t["id"] for t in search("certificate")] == ["t1"]


@respx.mock
def test_source_todo_skips_planner_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TODO_LISTS).respond(json={"value": []})
    planner_route = respx.get(PLANNER_ME).respond(json={"value": []})
    search("xyz", source="todo")
    assert planner_route.call_count == 0


@respx.mock
def test_source_planner_skips_todo_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    todo_route = respx.get(TODO_LISTS).respond(json={"value": []})
    respx.get(PLANNER_ME).respond(json={"value": []})
    search("xyz", source="planner")
    assert todo_route.call_count == 0


@respx.mock
def test_source_all_hits_both(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    todo_route = respx.get(TODO_LISTS).respond(json={"value": []})
    planner_route = respx.get(PLANNER_ME).respond(json={"value": []})
    search("xyz", source="all")
    assert todo_route.call_count == 1
    assert planner_route.call_count == 1


def test_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty query"):
        search("")


def test_rejects_whitespace_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty query"):
        search("   ")


def test_rejects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        search("x", limit=0)


def test_rejects_invalid_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="source must be"):
        search("x", source="email")


@respx.mock
def test_limit_truncates_combined_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": f"t{i}", "title": "match"} for i in range(10)]}
    )
    respx.get(PLANNER_ME).respond(json={"value": []})
    out = search("match", limit=3)
    assert len(out) == 3


@respx.mock
def test_no_matches_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": "t1", "title": "completely unrelated"}]}
    )
    respx.get(PLANNER_ME).respond(json={"value": []})
    assert search("zzz-nothing") == []


@respx.mock
def test_swallows_planner_403_in_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike assigned_to_me, search defensively swallows planner-403
    so a tenant where Planner is disabled can still search To Do."""
    _patch_get_token(monkeypatch)
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(json={"value": [{"id": "t1", "title": "match"}]})
    respx.get(PLANNER_ME).respond(403, json={"error": "no"})
    out = search("match")
    assert [t["id"] for t in out] == ["t1"]
