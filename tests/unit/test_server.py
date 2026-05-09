# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the FastMCP server skeleton."""

from __future__ import annotations

import pytest


def _build_fresh_server(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Force a fresh _build_server() call so env-var flips are reflected."""
    import importlib

    import microsoft_tasks_mcp.server as server_module

    importlib.reload(server_module)
    return server_module


def _registered_tool_names(mcp_instance) -> set[str]:  # type: ignore[no-untyped-def]
    """FastMCP exposes the tool list via the public list_tools coroutine.

    For unit tests we synchronously read the internal `_tool_manager`
    registry — it's the same data the public coroutine returns, but
    without needing an event loop just to enumerate.
    """
    return set(mcp_instance._tool_manager._tools.keys())


def test_login_tools_always_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TASKS_ALLOW_WRITES", raising=False)
    server_module = _build_fresh_server(monkeypatch)
    names = _registered_tool_names(server_module._build_server())
    assert "tasks_login_begin" in names
    assert "tasks_login_status" in names


def test_writes_disabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No write tools registered by default. v0.1 has no read tools yet
    either, so the only registered names are the two login tools."""
    monkeypatch.delenv("TASKS_ALLOW_WRITES", raising=False)
    server_module = _build_fresh_server(monkeypatch)
    names = _registered_tool_names(server_module._build_server())
    # As soon as v0.1 read tools land, more names appear here — but no
    # name starting with todo_*_create / planner_*_create yet.
    assert not any(n.endswith("_create") for n in names)
    assert not any(n.endswith("_update") for n in names)
    assert not any(n.endswith("_delete") for n in names)


def test_writes_enabled_does_not_break_login_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with TASKS_ALLOW_WRITES=true, login tools are still there."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    server_module = _build_fresh_server(monkeypatch)
    names = _registered_tool_names(server_module._build_server())
    assert "tasks_login_begin" in names
    assert "tasks_login_status" in names


def test_get_profile_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TASKS_PROFILE", raising=False)
    from microsoft_tasks_mcp.server import _get_profile

    assert _get_profile() == "default"


def test_get_profile_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TASKS_PROFILE", "harness")
    from microsoft_tasks_mcp.server import _get_profile

    assert _get_profile() == "harness"


def test_server_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server identifies itself by package name; MCP clients see this."""
    server_module = _build_fresh_server(monkeypatch)
    server = server_module._build_server()
    assert server.name == "mcp-server-microsoft-tasks"
