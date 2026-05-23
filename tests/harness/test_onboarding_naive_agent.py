# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: naive-agent onboarding scenario for #57.

The premise: a brand-new MCP client (Claude Code, Cursor, etc.) picks
up `mcp-server-microsoft-tasks` cold and tries to make it useful. The
agent has never seen this codebase, never read the README, and has no
prior knowledge of which env vars exist. It must be able to:

1. **Discover** the consent-gate env vars by reading `tasks_login_status`'s
   `available_flags` block.
2. **Diagnose** a `NOT_OWNED_BY_PROFILE` error and find the
   `TASKS_ALLOW_EXTERNAL_WRITES` unlock without consulting docs.
3. **Succeed** in completing an externally-created task once both
   flags are set.

The "naive agent" here is a deterministic Python script that does
keyword matching on tool descriptions and tool output. The point is
to assert what information the SERVER surfaces — not the LLM's
reasoning ability. If the server stops mentioning a flag in the
right place, this test breaks loudly.

Phases A and B inspect tool descriptions + structured responses
(no real Graph). Phase C exercises the full external-write path
against a mocked Graph (real httpx code path; only the network
layer is faked via respx). All phases use `_build_fresh_server()`
so the test sees the same registration / banner output as a real
MCP client at startup.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
import respx

GRAPH = "https://graph.microsoft.com/v1.0"
HARNESS_PROFILE = "harness"


def _build_fresh_server(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Reload + rebuild server so env-var changes during the test take
    effect. Mirrors the integration-test pattern in
    `tests/integration/test_planner_read_tools.py`."""
    import microsoft_tasks_mcp.server as server_module

    importlib.reload(server_module)
    return server_module._build_server()


def _registered(server, name: str):  # type: ignore[no-untyped-def]
    tool = server._tool_manager._tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "func", None) or tool


def _tool_description(server, name: str) -> str:  # type: ignore[no-untyped-def]
    """Surface the tool description string the way an MCP client would
    see it via `tools/list`. FastMCP stores it on the registered tool
    object."""
    tool = server._tool_manager._tools[name]
    return tool.description or ""


# Faux JWT-shape token so the personal-account detector returns False
# (work/school path) — keeps the planner guards out of the way. Real
# token claims are irrelevant; the integration tests stub at the HTTP
# layer.
_FAKE_TOKEN = "hdr.payload.sig"


def _patch_token_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch every tool module's local `get_token` binding. Module-level
    `from microsoft_tasks_mcp.auth import get_token` means each tool
    has its own reference that needs patching."""
    monkeypatch.setattr(
        "microsoft_tasks_mcp.auth.get_token", lambda profile=HARNESS_PROFILE: _FAKE_TOKEN
    )
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.login_status.get_token",
        lambda profile=HARNESS_PROFILE: _FAKE_TOKEN,
    )
    # todo_task_complete is a thin wrapper around todo_task_update — it
    # doesn't import get_token directly, so patching its binding errors.
    for mod_path in (
        "microsoft_tasks_mcp.tools.todo_task_update",
        "microsoft_tasks_mcp.tools.todo_task_delete",
    ):
        monkeypatch.setattr(f"{mod_path}.get_token", lambda profile: _FAKE_TOKEN)


# ---------------------------------------------------------------------
# Phase A — cold start, no flags set
# ---------------------------------------------------------------------


def test_phase_a_cold_start_status_surfaces_available_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naive agent calls `tasks_login_status`; the response must carry
    `available_flags` listing TASKS_ALLOW_WRITES as the next unlock,
    with a description naming the literal value "true". A keyword-
    matching agent reads the description and learns which env var to
    flip."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")  # required for _build_server
    monkeypatch.delenv("TASKS_ALLOW_EXTERNAL_WRITES", raising=False)
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    _patch_token_everywhere(monkeypatch)

    server = _build_fresh_server(monkeypatch)
    tasks_login_status = _registered(server, "tasks_login_status")

    # Cold-start agent: no Graph, no UPN cache. Patch /me so the probe
    # doesn't actually hit the network.
    with respx.mock:
        respx.get(f"{GRAPH}/me").respond(json={"userPrincipalName": "u@x.de"})
        result = tasks_login_status()

    # Discovery contract: available_flags is the canonical surface.
    assert "available_flags" in result, (
        "tasks_login_status MUST surface available_flags for naive-agent "
        "discovery — see #57 Phase A."
    )
    flags = result["available_flags"]

    # The naive agent reads each flag's description. For writes off, the
    # description must contain the literal "true" so the agent can guess
    # the value to set.
    writes_desc = flags["TASKS_ALLOW_WRITES"]
    assert "true" in writes_desc.lower(), (
        f"TASKS_ALLOW_WRITES description should hint at the value to set; got: {writes_desc!r}"
    )

    # writes_enabled reflects current state.
    assert result["writes_enabled"] is False


def test_phase_a_naive_agent_can_pick_the_writes_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end keyword match: simulate the naive agent's parser.
    Given the cold-start status output, the agent's goal is "enable
    write tools". Naive matcher: scan available_flags for any
    description containing the words 'create', 'update', or 'enable'
    plus 'task'. The flag whose description matches is the one to
    set."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "false")
    monkeypatch.delenv("TASKS_ALLOW_EXTERNAL_WRITES", raising=False)
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    _patch_token_everywhere(monkeypatch)

    server = _build_fresh_server(monkeypatch)
    tasks_login_status = _registered(server, "tasks_login_status")

    with respx.mock:
        respx.get(f"{GRAPH}/me").respond(json={"userPrincipalName": "u@x.de"})
        result = tasks_login_status()

    chosen = _naive_pick_flag_for_goal(result["available_flags"], goal="enable writes")
    assert chosen == "TASKS_ALLOW_WRITES", (
        f"Naive agent should pick TASKS_ALLOW_WRITES from the descriptions; "
        f"got {chosen!r}. Means the description text drifted from the "
        f"discoverability contract."
    )


# ---------------------------------------------------------------------
# Phase B — writes enabled, external-writes not yet set
# ---------------------------------------------------------------------


def test_phase_b_external_task_attempt_surfaces_external_writes_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent has TASKS_ALLOW_WRITES=true. It tries to complete a task
    NOT in this profile's registry. The error message must mention
    TASKS_ALLOW_EXTERNAL_WRITES so the agent can discover the unlock
    without leaving the chat."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    monkeypatch.delenv("TASKS_ALLOW_EXTERNAL_WRITES", raising=False)
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    _patch_token_everywhere(monkeypatch)

    server = _build_fresh_server(monkeypatch)
    todo_task_complete = _registered(server, "todo_task_complete")

    from microsoft_tasks_mcp.tools._writes_common import NotOwnedByProfileError

    with pytest.raises(NotOwnedByProfileError) as exc_info:
        todo_task_complete(task_id="EXT-T", list_id="EXT-L")

    error_message = str(exc_info.value)
    assert "TASKS_ALLOW_EXTERNAL_WRITES" in error_message, (
        f"NOT_OWNED_BY_PROFILE error MUST mention TASKS_ALLOW_EXTERNAL_WRITES "
        f"so a naive agent can discover the unlock from the error alone. "
        f"Got: {error_message!r}"
    )


def test_phase_b_status_describes_external_writes_after_writes_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Belt-and-braces: a Phase-B agent that re-checks tasks_login_status
    sees TASKS_ALLOW_WRITES as '(already enabled)' and
    TASKS_ALLOW_EXTERNAL_WRITES with an actionable description
    naming the cross-flag dependency."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    monkeypatch.delenv("TASKS_ALLOW_EXTERNAL_WRITES", raising=False)
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    _patch_token_everywhere(monkeypatch)

    server = _build_fresh_server(monkeypatch)
    tasks_login_status = _registered(server, "tasks_login_status")

    with respx.mock:
        respx.get(f"{GRAPH}/me").respond(json={"userPrincipalName": "u@x.de"})
        result = tasks_login_status()

    flags = result["available_flags"]
    assert flags["TASKS_ALLOW_WRITES"] == "(already enabled)"
    ext_desc = flags["TASKS_ALLOW_EXTERNAL_WRITES"]
    # Must name BOTH the value to set AND the cross-flag dependency.
    assert "true" in ext_desc.lower()
    assert "TASKS_ALLOW_WRITES" in ext_desc


# ---------------------------------------------------------------------
# Phase C — external-writes enabled, agent completes external task
# ---------------------------------------------------------------------


def test_phase_c_external_write_succeeds_against_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: both flags set, agent completes a task it didn't
    create. The tool fetches @odata.etag from a preliminary GET, then
    PATCHes with If-Match — the EXTERNALLY_MODIFIED guard still
    applies, only the ownership-by-this-MCP guard is relaxed."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    monkeypatch.setenv("TASKS_ALLOW_EXTERNAL_WRITES", "true")
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    _patch_token_everywhere(monkeypatch)

    with respx.mock:
        respx.get(f"{GRAPH}/me/todo/lists/EXT-L/tasks/EXT-T").respond(
            json={
                "id": "EXT-T",
                "title": "Manually typed task",
                "@odata.etag": 'W/"external"',
                "status": "notStarted",
            }
        )
        patch_route = respx.patch(f"{GRAPH}/me/todo/lists/EXT-L/tasks/EXT-T").respond(
            json={
                "id": "EXT-T",
                "title": "Manually typed task",
                "@odata.etag": 'W/"after"',
                "status": "completed",
            }
        )

        server = _build_fresh_server(monkeypatch)
        todo_task_complete = _registered(server, "todo_task_complete")
        result = todo_task_complete(task_id="EXT-T", list_id="EXT-L")

    # Phase C succeeded: agent acted on an external task.
    assert isinstance(result, dict)
    assert result.get("id") == "EXT-T"
    # If-Match was carried from the fresh GET, so the concurrent-write
    # safety contract still holds.
    assert patch_route.calls.last.request.headers["If-Match"] == 'W/"external"'
    # PATCH payload set status to completed
    sent = patch_route.calls.last.request.read().decode()
    assert '"completed"' in sent


def test_phase_c_external_write_without_list_id_fails_with_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the naive agent forgot to pass list_id, the error names
    list_id and the discovery tool (todo_lists) explicitly — so the
    agent's next move is obvious."""
    from microsoft_tasks_mcp.tools._writes_common import ExternalListIdRequiredError

    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    monkeypatch.setenv("TASKS_ALLOW_EXTERNAL_WRITES", "true")
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    _patch_token_everywhere(monkeypatch)

    server = _build_fresh_server(monkeypatch)
    todo_task_complete = _registered(server, "todo_task_complete")
    with pytest.raises(ExternalListIdRequiredError) as exc_info:
        todo_task_complete(task_id="EXT-T")
    msg = str(exc_info.value)
    assert "list_id" in msg
    assert "todo_lists" in msg


# ---------------------------------------------------------------------
# Cross-phase: write-tool descriptions name the consent gates
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name",
    [
        "todo_task_update",
        "todo_task_complete",
        "todo_task_delete",
    ],
)
def test_write_tool_descriptions_name_consent_gates(
    monkeypatch: pytest.MonkeyPatch, tool_name: str
) -> None:
    """Each write tool's MCP description MUST mention both consent
    gates verbatim — so a model reading the tools/list response can
    answer 'what env vars control this tool?' without leaving the
    chat. Acceptance criteria 2a in #57."""
    monkeypatch.setenv("TASKS_ALLOW_WRITES", "true")
    monkeypatch.delenv("TASKS_ALLOW_EXTERNAL_WRITES", raising=False)
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")

    server = _build_fresh_server(monkeypatch)
    description = _tool_description(server, tool_name)
    assert "TASKS_ALLOW_WRITES" in description, (
        f"{tool_name} description must name TASKS_ALLOW_WRITES — got: {description!r}"
    )
    assert "TASKS_ALLOW_EXTERNAL_WRITES" in description, (
        f"{tool_name} description must name TASKS_ALLOW_EXTERNAL_WRITES — got: {description!r}"
    )


# ---------------------------------------------------------------------
# Helpers — the naive agent's keyword matcher
# ---------------------------------------------------------------------


def _naive_pick_flag_for_goal(available_flags: dict[str, str], *, goal: str) -> str | None:
    """Deterministic keyword matcher: from `available_flags`, pick the
    env-var key whose description matches the goal best.

    For `goal="enable writes"`: pick the flag whose description
    contains both 'create' / 'update' and 'task' (or 'enable' and
    'write'). The point is that the description text is descriptive
    enough for a non-LLM string match — if it stops being so, the
    test breaks loudly and we know we lost the discovery surface.
    """
    if goal == "enable writes":
        for key, desc in available_flags.items():
            if desc == "(already enabled)":
                continue
            lowered = desc.lower()
            if ("create" in lowered or "enable" in lowered) and (
                "task" in lowered or "write" in lowered
            ):
                return key
        return None
    raise ValueError(f"unknown naive-agent goal: {goal!r}")


# Sanity: the helper itself does what we claim.
def test_naive_pick_flag_helper_picks_writes_for_writes_goal() -> None:
    flags = {
        "TASKS_ALLOW_WRITES": ("Set to 'true' to enable task creation, update, completion."),
        "TASKS_ALLOW_EXTERNAL_WRITES": (
            "Set to 'true' (requires TASKS_ALLOW_WRITES=true) to allow writes on external tasks."
        ),
    }
    assert _naive_pick_flag_for_goal(flags, goal="enable writes") == "TASKS_ALLOW_WRITES"


def test_naive_pick_flag_helper_skips_already_enabled() -> None:
    """An already-enabled flag (string sentinel `(already enabled)`)
    is skipped — the agent picks the NEXT actionable flag."""
    flags = {
        "TASKS_ALLOW_WRITES": "(already enabled)",
        "TASKS_ALLOW_EXTERNAL_WRITES": (
            "Set to 'true' (requires TASKS_ALLOW_WRITES=true) to enable "
            "writes on tasks the user typed manually."
        ),
    }
    chosen: Any = _naive_pick_flag_for_goal(flags, goal="enable writes")
    # In the already-enabled state, the next flag matches the keyword
    # set as well — proving the test isn't accidentally trivial.
    assert chosen == "TASKS_ALLOW_EXTERNAL_WRITES"
