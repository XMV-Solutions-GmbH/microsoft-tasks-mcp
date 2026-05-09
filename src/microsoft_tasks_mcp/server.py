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
from microsoft_tasks_mcp.tools.planner_buckets import (
    list_planner_buckets as _do_planner_buckets,
)
from microsoft_tasks_mcp.tools.planner_plan_get import (
    get_planner_plan as _do_planner_plan_get,
)
from microsoft_tasks_mcp.tools.planner_plans import (
    list_planner_plans as _do_planner_plans,
)
from microsoft_tasks_mcp.tools.planner_task_get import (
    get_planner_task as _do_planner_task_get,
)
from microsoft_tasks_mcp.tools.planner_tasks import (
    list_planner_tasks as _do_planner_tasks,
)
from microsoft_tasks_mcp.tools.tasks_assigned_to_me import (
    assigned_to_me as _do_tasks_assigned_to_me,
)
from microsoft_tasks_mcp.tools.tasks_search import search as _do_tasks_search
from microsoft_tasks_mcp.tools.tasks_status import status as _do_tasks_status
from microsoft_tasks_mcp.tools.todo_list_get import get_todo_list as _do_todo_list_get
from microsoft_tasks_mcp.tools.todo_lists import list_todo_lists as _do_todo_lists
from microsoft_tasks_mcp.tools.todo_task_get import get_todo_task as _do_todo_task_get
from microsoft_tasks_mcp.tools.todo_tasks import list_todo_tasks as _do_todo_tasks

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

    Currently registers the four Microsoft To Do read tools
    (`todo_lists`, `todo_list_get`, `todo_tasks`, `todo_task_get`).
    Planner + cross-source tools land in subsequent chunks.
    """

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Microsoft To Do Lists",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List the signed-in user's Microsoft To Do lists. Each "
            "list has `id`, `display_name`, `is_owner`, `is_shared`, "
            "`well_known_list_name` (e.g. 'defaultList' for the "
            "built-in Tasks list, 'flaggedEmails' for the Outlook "
            "flagged-mails list, or None for user-created lists), and "
            "`etag`. Read-only — does not modify anything. To list "
            "tasks within a list, pass the returned `id` to "
            "`todo_tasks`."
        ),
    )
    def todo_lists(limit: int = 50) -> list[dict[str, Any]]:
        return _do_todo_lists(limit=limit, profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Get Microsoft To Do List",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Fetch a single Microsoft To Do list by id. Same shape as "
            "an entry returned by `todo_lists`. Read-only."
        ),
    )
    def todo_list_get(list_id: str) -> dict[str, Any]:
        return _do_todo_list_get(list_id, profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Microsoft To Do Tasks",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List tasks in a Microsoft To Do list. Returns each task "
            "in the unified envelope: `id`, `title`, `status` "
            "(`completed`/`not_completed`), `due_date`, `assignees` "
            "(empty for To Do — per-user surface), `web_url` (None "
            "for To Do — no public deep-link), `source` (always "
            "`'todo'`), `etag` (for write concurrency), `list_id`, "
            "`body_preview`, `categories`, `importance`, "
            "`reminder_date`, `is_reminder_on`, "
            "`last_modified_date_time`, `created_date_time`. "
            "`status_filter` defaults to `'all'`; pass `'completed'` "
            "or `'not_completed'` to narrow."
        ),
    )
    def todo_tasks(
        list_id: str,
        status_filter: str = "all",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _do_todo_tasks(
            list_id,
            status_filter=status_filter,
            limit=limit,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Get Microsoft To Do Task",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Fetch one Microsoft To Do task by id within its list. "
            "Both `list_id` and `task_id` are required — Microsoft "
            "Graph has no global task-by-id endpoint for To Do. "
            "Returns the unified task envelope (same shape as items "
            "in `todo_tasks`). Read-only."
        ),
    )
    def todo_task_get(list_id: str, task_id: str) -> dict[str, Any]:
        return _do_todo_task_get(list_id, task_id, profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Microsoft Planner Plans",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List Microsoft Planner plans the signed-in user can see. "
            "Without `group_id`, enumerates the user's M365 groups via "
            "`/me/memberOf` (requires Group.Read.All admin-consent — "
            "already granted on the XMV-published OAuth app) and "
            "aggregates plans across them. With `group_id`, lists "
            "plans within that single group. Each plan has `id`, "
            "`title`, `owner_group_id`, `created_date_time`, `etag`. "
            "Read-only."
        ),
    )
    def planner_plans(
        group_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return _do_planner_plans(
            group_id=group_id,
            limit=limit,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Get Microsoft Planner Plan",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Fetch one Microsoft Planner plan by id. Same shape as an "
            "entry returned by `planner_plans`. Read-only."
        ),
    )
    def planner_plan_get(plan_id: str) -> dict[str, Any]:
        return _do_planner_plan_get(plan_id, profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Microsoft Planner Buckets",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List buckets (columns) within a Planner plan. Each bucket "
            "has `id`, `name`, `plan_id`, `order_hint`, `etag`. The "
            "`order_hint` follows Microsoft Graph's lexicographic "
            "ordering scheme (read-only — buckets ship pre-ordered as "
            "the user arranged them in Planner). Read-only."
        ),
    )
    def planner_buckets(plan_id: str) -> list[dict[str, Any]]:
        return _do_planner_buckets(plan_id, profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Microsoft Planner Tasks",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List tasks within a Planner plan. Returns each task in "
            "the unified envelope: `id`, `title`, `status` "
            "(`completed`/`not_completed` — derived from "
            "`percentComplete >= 100`), `due_date`, `assignees` (list "
            "of M365 user-ids assigned to the task), `web_url` (None "
            "until the tenant deep-link is wired in v0.2+), `source` "
            "(`'planner'`), `etag`, `plan_id`, `bucket_id`, "
            "`priority`, `percent_complete`, `applied_categories`, "
            "`created_date_time`, `last_modified_date_time`. "
            "Optionally narrow by `bucket_id` and `status_filter` "
            "(`'all'`/`'completed'`/`'not_completed'`)."
        ),
    )
    def planner_tasks(
        plan_id: str,
        bucket_id: str | None = None,
        status_filter: str = "all",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _do_planner_tasks(
            plan_id,
            bucket_id=bucket_id,
            status_filter=status_filter,
            limit=limit,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Get Microsoft Planner Task",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Fetch one Planner task by id. Returns the unified task "
            "envelope (same shape as items in `planner_tasks`). "
            "Pass `include_details=True` to additionally fetch the "
            "task's `description`, `checklist`, `references`, and "
            "`preview_type` (one extra Graph round-trip to "
            "`/planner/tasks/{id}/details`). Read-only."
        ),
    )
    def planner_task_get(
        task_id: str,
        include_details: bool = False,
    ) -> dict[str, Any]:
        return _do_planner_task_get(
            task_id,
            include_details=include_details,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Tasks Assigned to Me",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Cross-source view: every Microsoft To Do task in the "
            "user's lists plus every Microsoft Planner task assigned "
            "to the user, merged into one list. Sorted by `due_date` "
            "ascending (None last). `include_completed=False` "
            "excludes completed tasks from both surfaces. Each entry "
            "is a unified task envelope tagged with `source` "
            "(`'todo'` or `'planner'`) so the agent can route "
            "follow-up calls correctly. Read-only."
        ),
    )
    def tasks_assigned_to_me(
        include_completed: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _do_tasks_assigned_to_me(
            include_completed=include_completed,
            limit=limit,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Search Microsoft Tasks",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Case-insensitive substring search across the user's To "
            "Do tasks and Planner tasks. Matches against `title` and "
            "`body_preview`. `source` narrows to a single surface — "
            "`'all'` (default), `'todo'`, or `'planner'`. Returns up "
            "to `limit` matches in the unified envelope shape. "
            "Read-only. Note: implementation is client-side because "
            "neither surface exposes a server-side $search for tasks; "
            "performance is fine at typical task volumes (hundreds, "
            "not hundreds of thousands)."
        ),
    )
    def tasks_search(
        query: str,
        source: str = "all",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return _do_tasks_search(
            query,
            source=source,
            limit=limit,
            profile=_get_profile(),
        )


def register_write_tools(mcp_instance: FastMCP) -> None:
    """Register the v0.2 write tools (gated on `TASKS_ALLOW_WRITES=true`).

    Currently registers only `tasks_status` — the registry-inspection
    tool. The mutating tools (`*_task_create` / `_update` / `_complete`
    / `_delete`) land in subsequent v0.2 chunks.
    """

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Inspect Microsoft Tasks Created by This Profile",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Return every task this MCP profile created via the v0.2 "
            "write tools, with the last-known title, source "
            "(`'todo'` / `'planner'`), list_or_plan_id, etag, and "
            "creation timestamp. Used by the agent to remember its "
            "own outstanding work — and the **load-bearing safety "
            "guarantee** of v0.2: only tasks listed here can be "
            "modified by `*_task_update`, `*_task_complete`, or "
            "`*_task_delete`. Tasks created by humans or other "
            "agents are not in this registry and are protected from "
            "MCP-side modification. Read-only — does not hit Graph."
        ),
    )
    def tasks_status() -> list[dict[str, Any]]:
        return _do_tasks_status(profile=_get_profile())


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
