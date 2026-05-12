# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""End-to-end harness test for the v0.5 strict consent gate.

Confirms that the `TASKS_ALLOW_WRITES` env-var validation, OAuth scope
resolution, and `_build_server()` tool-registration all flow through
correctly when wired up against the real harness profile.

Skips gracefully if the harness profile token cache is empty.
"""

from __future__ import annotations

import importlib

import httpx
import pytest

from microsoft_tasks_mcp.auth import AuthRequiredError, get_token
from microsoft_tasks_mcp.auth.flow import (
    TasksConsentNotConfiguredError,
    resolve_scopes,
)

HARNESS_PROFILE = "harness"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _harness_token_or_skip() -> str:
    try:
        return get_token(HARNESS_PROFILE)
    except AuthRequiredError as exc:
        pytest.skip(
            f"Harness credentials not available: {exc}. "
            "Run `mcp-server-microsoft-tasks login --profile harness` to populate.",
        )


def test_consent_gate_writes_true_resolves_to_readwrite_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASKS_ALLOW_WRITES=true → resolve_scopes() replaces Tasks.Read with
    Tasks.ReadWrite. Pinned at the harness layer because the scope tuple
    is what gets sent to Microsoft Identity at login time — any drift
    between strings has real user-visible consent-screen consequences."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    monkeypatch.delenv("MS_TASKS_NO_PLANNER", raising=False)
    scopes = resolve_scopes()
    assert "Tasks.ReadWrite" in scopes
    assert "Tasks.Read" not in scopes
    assert "Group.Read.All" in scopes


def test_consent_gate_writes_false_resolves_to_readonly_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASKS_ALLOW_WRITES=false → resolve_scopes() requests Tasks.Read only.
    Consent screen on a fresh login won't mention writes."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    monkeypatch.delenv("MS_TASKS_NO_PLANNER", raising=False)
    scopes = resolve_scopes()
    assert "Tasks.Read" in scopes
    assert "Tasks.ReadWrite" not in scopes


def test_consent_gate_no_planner_drops_group_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Planner-disable toggle stays LENIENT (truthy-set, not strict
    true/false). Confirm the composition with writes-strict still
    produces the right scope tuple end-to-end."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    monkeypatch.setenv("MS_TASKS_NO_PLANNER", "true")
    scopes = resolve_scopes()
    assert "Group.Read.All" not in scopes
    assert "Tasks.Read" in scopes


def test_consent_gate_unset_raises_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error message is the user-facing onboarding doc — it must
    name the env var, both accepted values, and the file the operator
    edits."""
    monkeypatch.delenv("TASKS_ALLOW_WRITES", raising=False)
    with pytest.raises(TasksConsentNotConfiguredError) as exc_info:
        resolve_scopes()
    msg = str(exc_info.value)
    assert "TASKS_ALLOW_WRITES" in msg
    assert '"true"' in msg
    assert '"false"' in msg
    assert ".mcp.json" in msg


def test_consent_gate_harness_token_still_works_against_real_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The harness token was minted under v0.4 default scopes. After the
    v0.5 scope split it stays valid — Graph accepts a broader-scope
    token even when the client requests only narrower scopes on the
    NEXT refresh. Proves the upgrade doesn't strand existing setups."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    token = _harness_token_or_skip()

    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{GRAPH_BASE}/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    response.raise_for_status()
    assert response.json().get("id"), "Graph /me must return an id"


def test_consent_gate_build_server_writes_true_registers_write_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: with the harness token cached and TASKS_ALLOW_WRITES=true,
    _build_server() succeeds and exposes the gated write tools."""
    _harness_token_or_skip()
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    import microsoft_tasks_mcp.server as server_module

    importlib.reload(server_module)
    server = server_module._build_server()
    names = set(server._tool_manager._tools.keys())
    assert "todo_task_create" in names
    assert "planner_task_create" in names  # Planner default-on
    # Restore for sibling tests.
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    importlib.reload(server_module)


def test_consent_gate_build_server_writes_false_omits_write_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: TASKS_ALLOW_WRITES=false → no write tools."""
    _harness_token_or_skip()
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    import microsoft_tasks_mcp.server as server_module

    importlib.reload(server_module)
    server = server_module._build_server()
    names = set(server._tool_manager._tools.keys())
    assert "todo_task_create" not in names
    assert "planner_task_create" not in names
