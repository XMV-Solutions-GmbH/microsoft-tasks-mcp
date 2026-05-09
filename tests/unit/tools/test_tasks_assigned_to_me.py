# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for tasks_assigned_to_me."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.tasks_assigned_to_me import assigned_to_me

GRAPH = "https://graph.microsoft.com/v1.0"
PLANNER_ME = f"{GRAPH}/me/planner/tasks"
TODO_LISTS = f"{GRAPH}/me/todo/lists"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.tasks_assigned_to_me.get_token",
        lambda profile: token,
    )


@respx.mock
def test_merges_planner_and_todo(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {
                    "id": "p1",
                    "title": "Ship release",
                    "planId": "plan1",
                    "bucketId": "b1",
                    "percentComplete": 0,
                    "assignments": {"u": {}},
                    "dueDateTime": "2026-05-15T00:00:00Z",
                }
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={
            "value": [
                {
                    "id": "t1",
                    "title": "Buy gift",
                    "status": "notStarted",
                    "dueDateTime": {
                        "dateTime": "2026-05-10T00:00:00",
                        "timeZone": "UTC",
                    },
                }
            ]
        }
    )
    out = assigned_to_me()
    sources = [task["source"] for task in out]
    assert "todo" in sources and "planner" in sources
    assert len(out) == 2


@respx.mock
def test_sorts_by_due_date_ascending(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {
                    "id": "p-late",
                    "title": "Later planner",
                    "percentComplete": 0,
                    "assignments": {},
                    "dueDateTime": "2026-06-01T00:00:00Z",
                },
                {
                    "id": "p-early",
                    "title": "Earlier planner",
                    "percentComplete": 0,
                    "assignments": {},
                    "dueDateTime": "2026-05-01T00:00:00Z",
                },
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me()
    assert [t["id"] for t in out] == ["p-early", "p-late"]


@respx.mock
def test_no_due_date_sorts_last(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {
                    "id": "p-undated",
                    "title": "No due",
                    "percentComplete": 0,
                    "assignments": {},
                },
                {
                    "id": "p-dated",
                    "title": "Dated",
                    "percentComplete": 0,
                    "assignments": {},
                    "dueDateTime": "2026-05-01T00:00:00Z",
                },
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me()
    assert [t["id"] for t in out] == ["p-dated", "p-undated"]


@respx.mock
def test_excludes_completed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {"id": "p-done", "percentComplete": 100, "assignments": {}},
                {"id": "p-open", "percentComplete": 50, "assignments": {}},
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me(include_completed=False)
    assert [t["id"] for t in out] == ["p-open"]


@respx.mock
def test_include_completed_returns_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {"id": "p-done", "percentComplete": 100, "assignments": {}},
                {"id": "p-open", "percentComplete": 50, "assignments": {}},
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me(include_completed=True)
    assert {t["id"] for t in out} == {"p-done", "p-open"}


@respx.mock
def test_todo_filter_added_for_default_include_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    todo_route = respx.get(f"{TODO_LISTS}/L1/tasks").respond(json={"value": []})
    assigned_to_me()
    url = (
        str(todo_route.calls.last.request.url)
        .replace("%24", "$")
        .replace("%20", " ")
        .replace("+", " ")
        .replace("%27", "'")
    )
    assert "$filter=status ne 'completed'" in url


def test_rejects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        assigned_to_me(limit=0)


@respx.mock
def test_handles_planner_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """403 on planner should propagate (it's the same call for everyone
    — if the user can't read /me/planner/tasks at all, that's a real
    problem worth surfacing, not a per-list quirk to silently skip)."""
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(403, json={"error": "forbidden"})
    respx.get(TODO_LISTS).respond(json={"value": []})
    with pytest.raises(httpx.HTTPStatusError):
        assigned_to_me()


@respx.mock
def test_skips_individual_todo_list_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 on a single shared list is plausible and shouldn't kill
    the whole call."""
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "shared"}, {"id": "mine"}]})
    respx.get(f"{TODO_LISTS}/shared/tasks").respond(403, json={"error": "no"})
    respx.get(f"{TODO_LISTS}/mine/tasks").respond(
        json={
            "value": [
                {
                    "id": "t1",
                    "title": "ok",
                    "status": "notStarted",
                }
            ]
        }
    )
    out = assigned_to_me()
    assert [t["id"] for t in out] == ["t1"]


@respx.mock
def test_per_source_split_respects_overall_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [{"id": f"p{i}", "percentComplete": 0, "assignments": {}} for i in range(20)]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": f"t{i}", "title": "X", "status": "notStarted"} for i in range(20)]}
    )
    out = assigned_to_me(limit=4)
    assert len(out) == 4
