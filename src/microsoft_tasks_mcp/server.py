# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""MCP server: registers the tools with FastMCP and runs on stdio.

Each tool is wrapped with explicit `ToolAnnotations` so MCP clients
(notably Claude Code's permission system) can render the right prompt
— read-only tools get a different treatment from write ones.

**Read-only by default in v0.1.** Write tools land in v0.2 gated by
`TASKS_ALLOW_WRITES=true`; the gating constant is exposed here so
downstream tooling can import it without the registration plumbing
changing shape.

**Per-profile registry guarantee.** Even when v0.2 ships and writes
are enabled, every write tool refuses to act on a task whose ID is
not in this profile's "I created this" registry. The agent never
modifies tasks created by humans or other agents.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from microsoft_tasks_mcp.auth.flow import writes_enabled
from microsoft_tasks_mcp.tools.login_begin import login_begin as _do_login_begin
from microsoft_tasks_mcp.tools.login_status import login_status as _do_login_status

PROFILE_ENV = "TASKS_PROFILE"
DEFAULT_PROFILE = "default"


def _get_profile() -> str:
    return os.environ.get(PROFILE_ENV, DEFAULT_PROFILE)


def register_login_tools(mcp_instance: FastMCP) -> None:
    """Register the login MCP tools (always available).

    Order matters: register login tools before any other tools so
    error paths in the read tools can refer agents to `tasks_login_begin`
    when no token is cached.
    """

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Microsoft Tasks Login Status",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Return the current Microsoft 365 sign-in status for this "
            "profile. Three states: `signed_in` (a usable token exists, "
            "regardless of how it got there — CLI login, "
            "tasks_login_begin tool, even days ago), `pending` (a "
            "Device Code flow is in flight from a recent "
            "tasks_login_begin call; the response carries `user_code` + "
            "`verification_url` so the agent can re-display the "
            "prompt), or `none` (no token, no flow — the agent should "
            "call tasks_login_begin). Read-only: actively probes the "
            "token store + does at most one `/me` round-trip on a "
            "fresh signed_in to learn the UPN. "
            "When relaying a `pending` result to the user, render "
            "`user_code` FIRST in its own code block (no labels, no "
            "whitespace) and `verification_url` SECOND as a plain "
            "auto-link (not in a code block). The user copies the code "
            "first, then clicks the link, and pastes into the page "
            "that opens — minimises app-switching on mobile."
        ),
    )
    def tasks_login_status() -> dict[str, Any]:
        return _do_login_status(profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Microsoft Tasks Login Begin",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Drive the OAuth Device Code flow as an MCP tool. **Returns "
            "immediately, non-blocking.** Surfaces `user_code` + "
            "`verification_url` so the agent can show them; polls "
            "Microsoft Identity in the background until the user "
            "completes sign-in OR the device code expires (~15 min "
            "cap). The agent then polls `tasks_login_status` until it "
            "flips to `signed_in` (or to a terminal `expired` / "
            "`failed`). "
            "Idempotent: a non-expired pending session for the profile "
            "is returned as-is unless `force=True`. `force=True` "
            "cancels the in-flight session and starts a fresh flow. "
            "Returns the session's public view: `session_id`, "
            "`user_code`, `verification_url`, "
            "`verification_url_complete`, `expires_at`, "
            "`time_remaining_s`, `status`, `signed_in_user_upn`, "
            "`error`. "
            "When relaying the response to the user, render "
            "`user_code` FIRST in its own code block (no labels, no "
            "whitespace) and `verification_url` SECOND as a plain "
            "auto-link (not in a code block). The user copies the code "
            "first, then clicks the link, and pastes into the page "
            "that opens — minimises app-switching on mobile."
        ),
    )
    async def tasks_login_begin(
        force: bool = False,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, Any]:
        return await _do_login_begin(
            profile=_get_profile(),
            force=force,
            ctx=ctx,
        )


def register_read_tools(mcp_instance: FastMCP) -> None:
    """Register the unconditionally-available read tools.

    Placeholder for v0.1 — the To Do, Planner, and cross-source read
    tools will land in subsequent chunks. Calling this function on a
    server is a no-op until those tools are implemented.
    """
    del mcp_instance  # nothing to register yet


def register_write_tools(mcp_instance: FastMCP) -> None:
    """Register the write tools (v0.2, gated on `TASKS_ALLOW_WRITES=true`).

    Placeholder. Write tools are out of scope for v0.1.
    """
    del mcp_instance  # nothing to register yet


def _build_server() -> FastMCP:
    """Build and return a FastMCP server with the right tools registered."""
    server = FastMCP("mcp-server-microsoft-tasks")
    register_login_tools(server)
    register_read_tools(server)
    if writes_enabled():
        register_write_tools(server)
    else:
        logging.getLogger("microsoft-tasks-mcp").info(
            "TASKS_ALLOW_WRITES not set — read-only mode "
            "(write tools not registered). "
            "Set TASKS_ALLOW_WRITES=true to enable writes (v0.2+).",
        )
    return server


mcp: FastMCP = _build_server()


def run() -> None:
    """Start the MCP server on stdio. Blocks until stdin closes."""
    mcp.run()


# Suppress "imported but unused" — kept for future stderr-printing.
_ = sys
