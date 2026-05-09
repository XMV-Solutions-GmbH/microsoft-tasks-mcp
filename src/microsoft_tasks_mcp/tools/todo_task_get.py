# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_task_get — fetch a single Microsoft To Do task.

Wraps `GET /me/todo/lists/{listId}/tasks/{taskId}`. Read-only,
idempotent.

Note: Microsoft Graph requires both `list_id` and `task_id` to address
a To Do task — there is no global `/me/todo/tasks/{id}` endpoint.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers
from microsoft_tasks_mcp.tools._shape import todo_envelope


def get_todo_task(
    list_id: str,
    task_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch one To Do task by id within its list.

    Returns the unified task envelope (see `_shape.todo_envelope`).

    Raises:
        ValueError: empty list_id or task_id.
        httpx.HTTPStatusError: on a non-2xx response from Graph.
        microsoft_tasks_mcp.auth.AuthRequiredError: no usable cached
            token for `profile`.
    """
    if not list_id or not list_id.strip():
        raise ValueError("todo_task_get requires a non-empty list_id")
    if not task_id or not task_id.strip():
        raise ValueError("todo_task_get requires a non-empty task_id")

    list_id_s = list_id.strip()
    task_id_s = task_id.strip()

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me/todo/lists/{list_id_s}/tasks/{task_id_s}",
            headers=auth_headers(token),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("todo_task_get: Graph returned a non-object response")
        return todo_envelope(payload, list_id=list_id_s)
    finally:
        if http is None:
            client.close()
