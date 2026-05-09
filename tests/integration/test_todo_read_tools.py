# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Integration tests for the To Do read tools.

Cross-module wiring: tool registration through the FastMCP server,
auth-shim integration, end-to-end JSON shape preservation through the
public callable. Boundary mocks at the Microsoft Graph HTTP layer
(via respx); no real Graph traffic.
"""

from __future__ import annotations

import importlib

import pytest
import respx

LISTS_URL = "https://graph.microsoft.com/v1.0/me/todo/lists"


def _build_fresh_server(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    import microsoft_tasks_mcp.server as server_module

    importlib.reload(server_module)
    return server_module._build_server()


def _registered(server, name: str):  # type: ignore[no-untyped-def]
    """Look up a tool's underlying callable through FastMCP's tool manager."""
    tool = server._tool_manager._tools[name]
    # Tool stores the original Python function; older mcp-python uses
    # `.fn`, newer uses `.func`. Try both.
    return getattr(tool, "fn", None) or getattr(tool, "func", None) or tool


@pytest.fixture(autouse=True)
def _patch_token_in_each_tool_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass real auth across every To Do tool module so the
    integration tests focus on tool wiring + shape, not auth."""
    for mod_path in (
        "microsoft_tasks_mcp.tools.todo_lists",
        "microsoft_tasks_mcp.tools.todo_list_get",
        "microsoft_tasks_mcp.tools.todo_tasks",
        "microsoft_tasks_mcp.tools.todo_task_get",
    ):
        monkeypatch.setattr(f"{mod_path}.get_token", lambda profile: "AT-int")


@respx.mock
def test_todo_lists_registered_and_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TASKS_PROFILE", raising=False)
    respx.get(LISTS_URL).respond(json={"value": [{"id": "L1", "displayName": "Tasks"}]})

    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "todo_lists")
    out = fn(limit=10)
    assert isinstance(out, list) and len(out) == 1
    assert out[0]["id"] == "L1"


@respx.mock
def test_todo_list_get_registered_and_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(f"{LISTS_URL}/L9").respond(json={"id": "L9", "displayName": "Inbox"})
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "todo_list_get")
    out = fn("L9")
    assert out["id"] == "L9"


@respx.mock
def test_todo_tasks_registered_and_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(f"{LISTS_URL}/L1/tasks").respond(
        json={
            "value": [
                {
                    "id": "T1",
                    "title": "Buy milk",
                    "status": "notStarted",
                    "@odata.etag": 'W/"x"',
                }
            ]
        }
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "todo_tasks")
    out = fn("L1")
    assert len(out) == 1
    assert out[0]["title"] == "Buy milk"
    assert out[0]["status"] == "not_completed"
    assert out[0]["source"] == "todo"


@respx.mock
def test_todo_task_get_registered_and_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.get(f"{LISTS_URL}/L1/tasks/T9").respond(
        json={"id": "T9", "title": "X", "status": "completed"}
    )
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "todo_task_get")
    out = fn("L1", "T9")
    assert out["id"] == "T9"
    assert out["status"] == "completed"


def test_profile_env_threads_through_to_token_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASKS_PROFILE set at the env level must reach get_token via
    server._get_profile."""
    monkeypatch.setenv("TASKS_PROFILE", "harness")
    seen: dict[str, str] = {}

    def fake_get_token(profile: str) -> str:
        seen["profile"] = profile
        return "AT"

    monkeypatch.setattr("microsoft_tasks_mcp.tools.todo_lists.get_token", fake_get_token)

    with respx.mock:
        respx.get(LISTS_URL).respond(json={"value": []})
        server = _build_fresh_server(monkeypatch)
        fn = _registered(server, "todo_lists")
        fn(limit=5)

    assert seen["profile"] == "harness"


@respx.mock
def test_status_filter_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    route = respx.get(f"{LISTS_URL}/L1/tasks").respond(json={"value": []})
    server = _build_fresh_server(monkeypatch)
    fn = _registered(server, "todo_tasks")
    fn("L1", status_filter="completed")
    url = str(route.calls.last.request.url).replace("%24", "$")
    assert "$filter=status" in url
