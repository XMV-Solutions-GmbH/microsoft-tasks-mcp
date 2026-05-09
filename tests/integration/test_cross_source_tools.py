# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Integration tests for tasks_assigned_to_me + tasks_search."""

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
def _patch_token(monkeypatch: pytest.MonkeyPatch) -> None:
    for mod_path in (
        "microsoft_tasks_mcp.tools.tasks_assigned_to_me",
        "microsoft_tasks_mcp.tools.tasks_search",
    ):
        monkeypatch.setattr(f"{mod_path}.get_token", lambda profile: "AT")


@respx.mock
def test_tasks_assigned_to_me_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/me/planner/tasks").respond(
        json={"value": [{"id": "p1", "percentComplete": 0, "assignments": {"u": {}}}]}
    )
    respx.get(f"{GRAPH}/me/todo/lists").respond(json={"value": []})
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "tasks_assigned_to_me")
    out = fn()
    # v0.4 — return shape is now {"tasks": [...], "_skipped_profiles": [...]}.
    assert {t["source"] for t in out["tasks"]} == {"planner"}
    assert out["_skipped_profiles"] == []


@respx.mock
def test_tasks_search_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{GRAPH}/me/todo/lists").respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{GRAPH}/me/todo/lists/L1/tasks").respond(
        json={"value": [{"id": "t1", "title": "match-foo"}]}
    )
    respx.get(f"{GRAPH}/me/planner/tasks").respond(json={"value": []})
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "tasks_search")
    out = fn("match")
    assert [t["id"] for t in out] == ["t1"]


def test_cross_source_tools_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _build_fresh_server(monkeypatch)
    names = set(server._tool_manager._tools.keys())
    assert "tasks_assigned_to_me" in names
    assert "tasks_search" in names
