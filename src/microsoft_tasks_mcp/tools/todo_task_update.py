# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_task_update — update a Microsoft To Do task this profile created.

PATCH /me/todo/lists/{listId}/tasks/{taskId} with `If-Match` set to
the last-known ETag. Refuses to act on tasks not in this profile's
registry.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.auth.flow import external_writes_enabled
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers
from microsoft_tasks_mcp.tools._shape import todo_envelope
from microsoft_tasks_mcp.tools._writes_common import (
    ExternalListIdRequiredError,
    ExternallyModifiedError,
    require_owned_by_profile,
)

_VALID_STATUS = frozenset({"completed", "not_completed"})
_VALID_IMPORTANCE = frozenset({"low", "normal", "high"})


def update_todo_task(
    task_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    due_date: str | None = None,
    status: str | None = None,
    importance: str | None = None,
    list_id: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Patch a To Do task. Only fields explicitly passed are changed.

    `status` accepts the unified envelope values `"completed"` /
    `"not_completed"`; under the hood, `"not_completed"` maps to
    Graph's `notStarted`.

    `list_id` is OPTIONAL and only consulted when
    `TASKS_ALLOW_EXTERNAL_WRITES=true` AND the task isn't in this
    profile's registry — Microsoft Graph's To Do API requires the
    list id in the URL, so the agent must supply it for external
    tasks (discover via the `todo_lists` tool). When the task IS in
    the registry, `list_id` is ignored (the registry's value is
    authoritative).

    Refuses with `NotOwnedByProfileError` if `task_id` isn't in this
    profile's registry AND `TASKS_ALLOW_EXTERNAL_WRITES` is unset/false.
    Refuses with `ExternalListIdRequiredError` if external-writes is
    on but no `list_id` was provided for an external task. Refuses
    with `ExternallyModifiedError` if Microsoft Graph rejects the
    write because the underlying task changed since this profile last
    saw it (HTTP 412 Precondition Failed via `If-Match`).
    """
    if not task_id or not task_id.strip():
        raise ValueError("todo_task_update requires a non-empty task_id")
    if status is not None and status not in _VALID_STATUS:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUS)} or None, got {status!r}")
    if importance is not None and importance not in _VALID_IMPORTANCE:
        raise ValueError(
            f"importance must be one of {sorted(_VALID_IMPORTANCE)} or None, got {importance!r}"
        )

    task_id_s = task_id.strip()
    reg = registry if registry is not None else TaskRegistry(profile)
    allow_ext = external_writes_enabled()
    entry = require_owned_by_profile(
        registry=reg,
        graph_id=task_id_s,
        expected_source="todo",
        allow_external=allow_ext,
    )

    payload: dict[str, Any] = {}
    if title is not None:
        if not title.strip():
            raise ValueError("title, when given, must not be empty")
        payload["title"] = title.strip()
    if body is not None:
        payload["body"] = {"content": body, "contentType": "text"}
    if due_date is not None:
        payload["dueDateTime"] = {"dateTime": due_date, "timeZone": "UTC"}
    if status is not None:
        payload["status"] = "completed" if status == "completed" else "notStarted"
    if importance is not None:
        payload["importance"] = importance

    if not payload:
        raise ValueError(
            "todo_task_update requires at least one field to update "
            "(title / body / due_date / status / importance)",
        )

    token = get_token(profile)
    headers: dict[str, str] = {
        **auth_headers(token),
        "Content-Type": "application/json",
    }

    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        if entry is not None:
            # In-registry path: use cached list_id + etag.
            target_list_id = entry.list_or_plan_id
            cached_etag = entry.etag
        else:
            # External-writes path (TASKS_ALLOW_EXTERNAL_WRITES=true): the
            # agent must supply list_id (Graph has no /me/todo/tasks/{id}
            # shape). Fetch fresh @odata.etag for concurrent-write safety.
            if not list_id or not list_id.strip():
                raise ExternalListIdRequiredError(task_id_s)
            target_list_id = list_id.strip()
            get_resp = client.get(
                f"{GRAPH_BASE}/me/todo/lists/{target_list_id}/tasks/{task_id_s}",
                headers=auth_headers(token),
            )
            get_resp.raise_for_status()
            get_payload = get_resp.json()
            cached_etag = get_payload.get("@odata.etag") if isinstance(get_payload, dict) else None

        if cached_etag:
            headers["If-Match"] = cached_etag

        response = client.patch(
            f"{GRAPH_BASE}/me/todo/lists/{target_list_id}/tasks/{task_id_s}",
            headers=headers,
            json=payload,
        )
        if response.status_code == 412:
            raise ExternallyModifiedError(task_id_s)
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise ValueError("todo_task_update: Graph returned a non-object response")
        envelope = todo_envelope(raw, list_id=target_list_id)
    finally:
        if http is None:
            client.close()

    # Only update the registry entry's etag when the task IS in the
    # registry — external tasks don't get a synthetic entry.
    if entry is not None:
        new_etag = envelope.get("etag") if isinstance(envelope.get("etag"), str) else None
        reg.update_etag(task_id_s, new_etag)
    return envelope
