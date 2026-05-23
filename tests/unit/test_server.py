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
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    server_module = _build_fresh_server(monkeypatch)
    names = _registered_tool_names(server_module._build_server())
    assert "tasks_login_begin" in names
    assert "tasks_login_status" in names


def test_login_tool_descriptions_carry_agent_instructions_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both tasks_login_begin and tasks_login_status MUST embed the literal
    `AGENT_INSTRUCTIONS:` marker — closes #49. The marker is the contract
    with pattern-matching MCP clients."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    server_module = _build_fresh_server(monkeypatch)
    server = server_module._build_server()
    tools = server._tool_manager._tools
    for name in ("tasks_login_begin", "tasks_login_status"):
        tool = tools[name]
        description = tool.description or ""
        assert "AGENT_INSTRUCTIONS:" in description, (
            f"{name} description must include the literal "
            f"'AGENT_INSTRUCTIONS:' marker; got: {description!r}"
        )
        assert "fenced code block" in description
        assert "markdown link" in description


def test_writes_disabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No write tools registered by default. v0.1 has no read tools yet
    either, so the only registered names are the two login tools."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
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


def test_tasks_status_only_with_writes_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    server_module = _build_fresh_server(monkeypatch)
    names_off = _registered_tool_names(server_module._build_server())
    assert "tasks_status" not in names_off

    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    server_module = _build_fresh_server(monkeypatch)
    names_on = _registered_tool_names(server_module._build_server())
    assert "tasks_status" in names_on


# ---------------------------------------------------------------------
# MS_TASKS_NO_PLANNER opt-out
# ---------------------------------------------------------------------


_PLANNER_READ_TOOLS = {
    "planner_plans",
    "planner_plan_get",
    "planner_buckets",
    "planner_tasks",
    "planner_task_get",
}
_PLANNER_WRITE_TOOLS = {
    "planner_task_create",
    "planner_task_update",
    "planner_task_complete",
    "planner_task_delete",
}
_TODO_READ_TOOLS = {"todo_lists", "todo_list_get", "todo_tasks", "todo_task_get"}


def test_planner_reads_registered_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MS_TASKS_NO_PLANNER", raising=False)
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    names = _registered_tool_names(_build_fresh_server(monkeypatch)._build_server())
    assert _PLANNER_READ_TOOLS.issubset(names)


def test_planner_reads_skipped_when_no_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MS_TASKS_NO_PLANNER", "true")
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    names = _registered_tool_names(_build_fresh_server(monkeypatch)._build_server())
    assert names.isdisjoint(_PLANNER_READ_TOOLS)
    # To Do reads still present
    assert _TODO_READ_TOOLS.issubset(names)
    # Cross-source tools still present (they skip the planner half internally)
    assert "tasks_assigned_to_me" in names
    assert "tasks_search" in names
    # Login tools still present
    assert "tasks_login_status" in names


def test_planner_writes_skipped_when_no_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MS_TASKS_NO_PLANNER", "true")
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    names = _registered_tool_names(_build_fresh_server(monkeypatch)._build_server())
    assert names.isdisjoint(_PLANNER_WRITE_TOOLS)
    # To Do writes still register
    assert "todo_task_create" in names
    assert "todo_task_update" in names
    assert "tasks_status" in names


def test_planner_writes_registered_with_writes_and_no_no_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MS_TASKS_NO_PLANNER", raising=False)
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    names = _registered_tool_names(_build_fresh_server(monkeypatch)._build_server())
    assert _PLANNER_WRITE_TOOLS.issubset(names)


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


# ---------------------------------------------------------------------
# v0.5 strict consent gate
# ---------------------------------------------------------------------


def test_build_server_refuses_when_consent_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_server raises TasksConsentNotConfiguredError when TASKS_ALLOW_WRITES unset.

    The reload itself raises (because the module-top-level
    `mcp = _build_server()` line fires during reload). That's the
    contract: an MCP-client launching the server with unset env sees
    an immediate startup error, not a deferred mid-protocol surprise.
    """
    monkeypatch.delenv("TASKS_ALLOW_WRITES", raising=False)
    import importlib

    import microsoft_tasks_mcp.server as server_module
    from microsoft_tasks_mcp.auth.flow import TasksConsentNotConfiguredError

    with pytest.raises(TasksConsentNotConfiguredError, match="not set"):
        importlib.reload(server_module)
    # Re-restore a valid module state for subsequent tests by re-loading
    # with a safe value (the conftest's setdefault gave us "false" in
    # the parent process, but reload bypasses that).
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    importlib.reload(server_module)


def test_build_server_refuses_on_legacy_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.4 legacy `TASKS_ALLOW_WRITES=yes` is rejected — must be explicit true/false."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "yes")
    import importlib

    import microsoft_tasks_mcp.server as server_module
    from microsoft_tasks_mcp.auth.flow import TasksConsentNotConfiguredError

    with pytest.raises(TasksConsentNotConfiguredError, match="TASKS_ALLOW_WRITES"):
        importlib.reload(server_module)
    # Restore for subsequent tests.
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    importlib.reload(server_module)


def test_build_server_consent_false_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit TASKS_ALLOW_WRITES=false → server builds in read-only mode."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    server_module = _build_fresh_server(monkeypatch)
    server = server_module._build_server()
    names = _registered_tool_names(server)
    # Read-mode: login + read tools but no writes
    assert "tasks_login_begin" in names
    assert not any(n.endswith("_create") for n in names)


def test_build_server_consent_true_registers_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit TASKS_ALLOW_WRITES=true → write tools registered."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    server_module = _build_fresh_server(monkeypatch)
    server = server_module._build_server()
    names = _registered_tool_names(server)
    assert "todo_task_create" in names
    assert "planner_task_create" in names  # default-on Planner


# ---------------------------------------------------------------------
# _guard_planner_account_type — personal-account refusal
# ---------------------------------------------------------------------


def _fake_jwt_with_tid(tid: str) -> str:
    """Compose a 3-segment JWT-shaped string with the given `tid` claim.

    Signature is junk — `is_personal_account()` decodes claims without
    verification (the token already passed Microsoft's checks upstream).
    """
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"tid": tid}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def test_guard_planner_refuses_personal_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Personal MSAs can't access Planner — Microsoft platform restriction,
    not XMV policy. The guard raises with a message naming the alternative
    (`todo_*` tools)."""
    from microsoft_tasks_mcp.auth.account_type import CONSUMER_TENANT_ID
    from microsoft_tasks_mcp.server import _guard_planner_account_type

    monkeypatch.setattr(
        "microsoft_tasks_mcp.server.get_token",
        lambda profile="default": _fake_jwt_with_tid(CONSUMER_TENANT_ID),
    )
    with pytest.raises(PermissionError, match="personal Microsoft account"):
        _guard_planner_account_type("default")


def test_guard_planner_allows_work_school_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Work/school tid → Planner is available, guard short-circuits."""
    from microsoft_tasks_mcp.server import _guard_planner_account_type

    monkeypatch.setattr(
        "microsoft_tasks_mcp.server.get_token",
        lambda profile="default": _fake_jwt_with_tid("7be9152f-5514-4a2d-b3d1-9aa5acf966c8"),
    )
    _guard_planner_account_type("default")  # no exception


def test_guard_planner_error_mentions_todo_alternative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error message tells the agent what DOES work (`todo_*`) so it
    can offer the user an alternative rather than giving up."""
    from microsoft_tasks_mcp.auth.account_type import CONSUMER_TENANT_ID
    from microsoft_tasks_mcp.server import _guard_planner_account_type

    monkeypatch.setattr(
        "microsoft_tasks_mcp.server.get_token",
        lambda profile="default": _fake_jwt_with_tid(CONSUMER_TENANT_ID),
    )
    with pytest.raises(PermissionError) as exc_info:
        _guard_planner_account_type("default")
    assert "todo_" in str(exc_info.value)
