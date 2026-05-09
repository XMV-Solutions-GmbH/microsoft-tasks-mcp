# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""tasks_assigned_to_me — unified cross-source view of the user's tasks.

Per `docs/app-concept.md` § Open tech-spike Q2: there is no single
Microsoft Graph endpoint that returns "every task assigned to me
across both To Do and Planner". We make two calls:

- **Planner**: `GET /me/planner/tasks` — clean, returns every Planner
  task assigned to the current user.
- **To Do**: enumerate `/me/todo/lists`, then for each list
  `/me/todo/lists/{id}/tasks` (filtered server-side when possible).
  To Do is per-user and has no assignee concept, so "assigned to me"
  in the To Do half means "any of the user's tasks".

Both halves are merged client-side. Sorted by due_date ascending
(None last). Per-source cap is `limit // 2` so neither side starves
the other on large lists.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.auth.flow import planner_disabled
from microsoft_tasks_mcp.tools._common import (
    GRAPH_BASE,
    auth_headers,
    tenant_id_from_token,
)
from microsoft_tasks_mcp.tools._shape import planner_envelope, todo_envelope


def assigned_to_me(
    *,
    include_completed: bool = False,
    limit: int = 100,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Return tasks currently assigned to the signed-in user across To
    Do + Planner.

    `include_completed=False` (default) excludes completed tasks from
    both surfaces. `limit` caps the merged result at that many entries
    overall, splitting the budget evenly across the two sources.
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    per_source = max(1, limit // 2)

    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        if planner_disabled():
            planner_tasks: list[dict[str, Any]] = []
        else:
            planner_tasks = _fetch_planner(
                client=client,
                token=token,
                tenant_id=tenant_id,
                include_completed=include_completed,
                limit=per_source,
            )
        todo_tasks = _fetch_todo(
            client=client,
            token=token,
            include_completed=include_completed,
            limit=per_source,
        )
    finally:
        if http is None:
            client.close()

    merged = todo_tasks + planner_tasks
    merged.sort(key=_sort_key)
    return merged[:limit]


def _fetch_planner(
    *,
    client: httpx.Client,
    token: str,
    tenant_id: str | None,
    include_completed: bool,
    limit: int,
) -> list[dict[str, Any]]:
    response = client.get(
        f"{GRAPH_BASE}/me/planner/tasks",
        headers=auth_headers(token),
        params={"$top": limit * 2},  # over-fetch so post-filter still has signal
    )
    response.raise_for_status()
    payload = response.json()
    raw = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for task in raw:
        if len(out) >= limit:
            break
        if not isinstance(task, dict):
            continue
        envelope = planner_envelope(task, tenant_id=tenant_id)
        if not include_completed and envelope["status"] == "completed":
            continue
        out.append(envelope)
    return out


def _fetch_todo(
    *,
    client: httpx.Client,
    token: str,
    include_completed: bool,
    limit: int,
) -> list[dict[str, Any]]:
    """Enumerate the user's To Do lists and pull tasks from each, up to
    `limit` total."""
    lists_response = client.get(
        f"{GRAPH_BASE}/me/todo/lists",
        headers=auth_headers(token),
    )
    lists_response.raise_for_status()
    lists_payload = lists_response.json()
    raw_lists = lists_payload.get("value") if isinstance(lists_payload, dict) else None
    if not isinstance(raw_lists, list):
        return []

    out: list[dict[str, Any]] = []
    for entry in raw_lists:
        if len(out) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        list_id = entry.get("id")
        if not isinstance(list_id, str):
            continue

        params: dict[str, str | int] = {"$top": max(1, limit - len(out))}
        if not include_completed:
            params["$filter"] = "status ne 'completed'"

        try:
            tasks_response = client.get(
                f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks",
                headers=auth_headers(token),
                params=params,
            )
            tasks_response.raise_for_status()
        except httpx.HTTPStatusError:
            # Skip lists where Graph returns 4xx (rare, e.g. shared
            # list whose owner revoked access mid-call).
            continue

        tasks_payload = tasks_response.json()
        raw_tasks = tasks_payload.get("value") if isinstance(tasks_payload, dict) else None
        if not isinstance(raw_tasks, list):
            continue
        for task in raw_tasks:
            if len(out) >= limit:
                break
            if not isinstance(task, dict):
                continue
            out.append(todo_envelope(task, list_id=list_id))
    return out


def _sort_key(task: dict[str, Any]) -> tuple[int, str]:
    """Sort by due_date ascending; entries with no due_date go last."""
    due = task.get("due_date")
    if isinstance(due, str) and due:
        return (0, due)
    return (1, "")
