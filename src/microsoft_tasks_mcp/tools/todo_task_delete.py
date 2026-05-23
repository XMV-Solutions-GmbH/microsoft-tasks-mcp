# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_task_delete — delete a profile-owned Microsoft To Do task.

DELETE /me/todo/lists/{listId}/tasks/{taskId}. Refuses to act on
tasks not in this profile's registry. Idempotent: a 404 from Graph
(task already gone server-side) is treated as success and the
registry entry is cleaned up either way.
"""

from __future__ import annotations

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.auth.flow import external_writes_enabled
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers
from microsoft_tasks_mcp.tools._writes_common import (
    ExternalListIdRequiredError,
    require_owned_by_profile,
)


def delete_todo_task(
    task_id: str,
    *,
    list_id: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> None:
    """Delete a To Do task this profile created.

    `list_id` is OPTIONAL and only consulted when
    `TASKS_ALLOW_EXTERNAL_WRITES=true` AND the task isn't in this
    profile's registry. Discover list ids via the `todo_lists` tool.

    Idempotent: re-deleting a task already gone server-side is a
    silent no-op (the registry entry, if any, is cleaned up either
    way).
    """
    if not task_id or not task_id.strip():
        raise ValueError("todo_task_delete requires a non-empty task_id")

    task_id_s = task_id.strip()
    reg = registry if registry is not None else TaskRegistry(profile)
    allow_ext = external_writes_enabled()
    entry = require_owned_by_profile(
        registry=reg,
        graph_id=task_id_s,
        expected_source="todo",
        allow_external=allow_ext,
    )

    if entry is not None:
        target_list_id = entry.list_or_plan_id
    else:
        if not list_id or not list_id.strip():
            raise ExternalListIdRequiredError(task_id_s)
        target_list_id = list_id.strip()

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.delete(
            f"{GRAPH_BASE}/me/todo/lists/{target_list_id}/tasks/{task_id_s}",
            headers=auth_headers(token),
        )
        if response.status_code == 404:
            # Already gone server-side; clean up the (possibly absent)
            # registry entry and return.
            reg.remove(task_id_s)
            return
        response.raise_for_status()
    finally:
        if http is None:
            client.close()

    reg.remove(task_id_s)
