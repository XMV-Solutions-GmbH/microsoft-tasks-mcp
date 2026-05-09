# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Integration tests for the Planner read tools.

Boundary mocks at the Microsoft Graph HTTP layer (via respx). Exercises
tool registration, env-driven profile threading, and end-to-end JSON
shape preservation.
"""

from __future__ import annotations

import importlib

import pytest
import respx

GRAPH = "https://graph.microsoft.com/v1.0"


def _build_fresh_server(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    import microsoft_tasks_mcp.server as server_module

    importlib.reload(server_module)
    return server_module._build_server()


def _registered(server, name: str):  # type: ignore[no-untyped-def]
    tool = server._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "func", None) or tool


@pytest.fixture(autouse=True)
def _patch_token_in_each_tool_module(monkeypatch: pytest.MonkeyPatch) -> None:
    for mod_path in (
        "microsoft_tasks_mcp.tools.planner_plans",
        "microsoft_tasks_mcp.tools.planner_plan_get",
        "microsoft_tasks_mcp.tools.planner_buckets",
        "microsoft_tasks_mcp.tools.planner_tasks",
        "microsoft_tasks_mcp.tools.planner_task_get",
    ):
        monkeypatch.setattr(f"{mod_path}.get_token", lambda profile: "AT-int")


@respx.mock
def test_planner_plans_with_group_id(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/groups/g1/planner/plans").respond(
        json={"value": [{"id": "p1", "title": "Sprint"}]}
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "planner_plans")
    out = fn(group_id="g1", limit=10)
    assert out[0]["id"] == "p1"


@respx.mock
def test_planner_plans_aggregates_across_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/me/memberOf").respond(
        json={"value": [{"id": "g1", "groupTypes": ["Unified"]}]}
    )
    respx.get(f"{GRAPH}/groups/g1/planner/plans").respond(
        json={"value": [{"id": "p1", "title": "X"}]}
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "planner_plans")
    out = fn()
    assert out[0]["id"] == "p1"


@respx.mock
def test_planner_plan_get(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/planner/plans/p1").respond(json={"id": "p1", "title": "Sprint"})
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "planner_plan_get")
    assert fn("p1")["id"] == "p1"


@respx.mock
def test_planner_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/planner/plans/p1/buckets").respond(
        json={"value": [{"id": "b1", "name": "Todo", "planId": "p1"}]}
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "planner_buckets")
    out = fn("p1")
    assert out[0]["name"] == "Todo"


@respx.mock
def test_planner_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/planner/plans/p1/tasks").respond(
        json={
            "value": [
                {
                    "id": "t1",
                    "title": "Ship",
                    "planId": "p1",
                    "bucketId": "b1",
                    "percentComplete": 50,
                    "assignments": {},
                }
            ]
        }
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "planner_tasks")
    out = fn("p1")
    assert out[0]["source"] == "planner"
    assert out[0]["status"] == "not_completed"


@respx.mock
def test_planner_tasks_status_filter_through_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(f"{GRAPH}/planner/plans/p1/tasks").respond(
        json={
            "value": [
                {"id": "t1", "percentComplete": 0, "assignments": {}},
                {"id": "t2", "percentComplete": 100, "assignments": {}},
            ]
        }
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "planner_tasks")
    out = fn("p1", status_filter="completed")
    assert {t["id"] for t in out} == {"t2"}


@respx.mock
def test_planner_task_get_with_details(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/planner/tasks/t1").respond(
        json={"id": "t1", "title": "X", "percentComplete": 0, "assignments": {}}
    )
    respx.get(f"{GRAPH}/planner/tasks/t1/details").respond(
        json={"description": "body", "checklist": {}, "references": {}}
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "planner_task_get")
    out = fn("t1", include_details=True)
    assert out["description"] == "body"


def test_planner_tools_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _build_fresh_server(monkeypatch)
    names = set(server._tool_manager._tools.keys())
    assert "planner_plans" in names
    assert "planner_plan_get" in names
    assert "planner_buckets" in names
    assert "planner_tasks" in names
    assert "planner_task_get" in names
