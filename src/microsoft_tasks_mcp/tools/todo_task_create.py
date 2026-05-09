# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_task_create — create a new Microsoft To Do task.

POST /me/todo/lists/{listId}/tasks. Adds the new task to this profile's
registry so subsequent _update / _complete / _delete tools can safely
mutate it.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry, now
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers
from microsoft_tasks_mcp.tools._shape import todo_envelope

_VALID_IMPORTANCE = frozenset({"low", "normal", "high"})


def create_todo_task(
    list_id: str,
    title: str,
    *,
    body: str | None = None,
    due_date: str | None = None,
    importance: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Create a To Do task in `list_id`.

    `due_date` is an ISO 8601 timestamp; treated as UTC. `importance`
    is `"low"` / `"normal"` / `"high"` per Microsoft Graph.

    Returns the unified envelope of the new task. Adds the new task's
    `graph_id` to this profile's registry.
    """
    if not list_id or not list_id.strip():
        raise ValueError("todo_task_create requires a non-empty list_id")
    if not title or not title.strip():
        raise ValueError("todo_task_create requires a non-empty title")
    if importance is not None and importance not in _VALID_IMPORTANCE:
        raise ValueError(
            f"importance must be one of {sorted(_VALID_IMPORTANCE)} or None, got {importance!r}",
        )

    list_id_s = list_id.strip()
    payload: dict[str, Any] = {"title": title.strip()}
    if body is not None:
        payload["body"] = {"content": body, "contentType": "text"}
    if due_date is not None:
        payload["dueDateTime"] = {"dateTime": due_date, "timeZone": "UTC"}
    if importance is not None:
        payload["importance"] = importance

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.post(
            f"{GRAPH_BASE}/me/todo/lists/{list_id_s}/tasks",
            headers={**auth_headers(token), "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise ValueError("todo_task_create: Graph returned a non-object response")
        envelope = todo_envelope(raw, list_id=list_id_s)
    finally:
        if http is None:
            client.close()

    reg = registry if registry is not None else TaskRegistry(profile)
    graph_id = envelope.get("id")
    if isinstance(graph_id, str):
        reg.add(
            TaskEntry(
                source="todo",
                graph_id=graph_id,
                list_or_plan_id=list_id_s,
                title=envelope.get("title") or title.strip(),
                etag=envelope.get("etag"),
                created_at=now(),
            )
        )
    return envelope
