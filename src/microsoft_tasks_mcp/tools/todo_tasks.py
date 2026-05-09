# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_tasks — list tasks within a Microsoft To Do list.

Wraps `GET /me/todo/lists/{listId}/tasks`. Read-only, idempotent.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers
from microsoft_tasks_mcp.tools._shape import todo_envelope

_VALID_STATUS_FILTERS = frozenset({"all", "completed", "not_completed"})


def list_todo_tasks(
    list_id: str,
    *,
    status_filter: str = "all",
    limit: int = 100,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List tasks in a To Do list.

    Returns at most `limit` tasks in the unified envelope shape (see
    `_shape.todo_envelope` and `docs/app-concept.md`).

    `status_filter`:
    - `"all"` (default): every task regardless of state.
    - `"not_completed"`: every task whose Graph status is not
      `completed` (covers notStarted / inProgress / waitingOnOthers /
      deferred — i.e. "still on the user's plate").
    - `"completed"`: only completed tasks.

    Raises:
        ValueError: empty list_id, non-positive limit, or unknown
            status_filter.
        httpx.HTTPStatusError: on a non-2xx response from Graph.
        microsoft_tasks_mcp.auth.AuthRequiredError: no usable cached
            token for `profile`.
    """
    if not list_id or not list_id.strip():
        raise ValueError("todo_tasks requires a non-empty list_id")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    if status_filter not in _VALID_STATUS_FILTERS:
        raise ValueError(
            f"status_filter must be one of {sorted(_VALID_STATUS_FILTERS)}, got {status_filter!r}",
        )

    params: dict[str, str | int] = {"$top": limit}
    if status_filter == "completed":
        params["$filter"] = "status eq 'completed'"
    elif status_filter == "not_completed":
        params["$filter"] = "status ne 'completed'"

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me/todo/lists/{list_id.strip()}/tasks",
            headers=auth_headers(token),
            params=params,
        )
        response.raise_for_status()
        return _extract_tasks(response.json(), list_id=list_id.strip())
    finally:
        if http is None:
            client.close()


def _extract_tasks(payload: dict[str, Any], *, list_id: str) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for task in raw:
        if not isinstance(task, dict):
            continue
        out.append(todo_envelope(task, list_id=list_id))
    return out
