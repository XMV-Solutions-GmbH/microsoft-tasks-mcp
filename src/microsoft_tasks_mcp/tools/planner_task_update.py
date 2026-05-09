# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_task_update — update a profile-owned Planner task.

PATCH /planner/tasks/{taskId} with `If-Match: <last-known etag>`.
Refuses NOT_OWNED_BY_PROFILE. Refuses EXTERNALLY_MODIFIED on 412.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools._common import (
    PLANNER_BETA_ENV,
    auth_headers,
    graph_planner_base,
    planner_beta_enabled,
    tenant_id_from_token,
)
from microsoft_tasks_mcp.tools._shape import planner_envelope
from microsoft_tasks_mcp.tools._writes_common import (
    ExternallyModifiedError,
    require_owned_by_profile,
    validate_planner_recurrence,
)

_VALID_STATUS = frozenset({"completed", "not_completed"})

# Sentinel: pass `recurrence=_UNSET` (the default) to leave recurrence
# untouched. `recurrence=None` is reserved for callers who want to
# *try* clearing — Graph rejects it on tasks that already have
# recurrence (it must be cleared via `recurrence={"schedule": None}`),
# so we forward None to Graph and let it surface the error.
_UNSET: Any = object()


def update_planner_task(
    task_id: str,
    *,
    title: str | None = None,
    bucket_id: str | None = None,
    due_date: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    recurrence: Any = _UNSET,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Patch a Planner task. Only fields explicitly passed are changed.

    `status` accepts the unified envelope values; `"completed"` maps
    to `percentComplete=100` on the wire, `"not_completed"` to `0`.

    `priority` is an integer 0..10 (Planner's range; convention is
    1=urgent, 3=important, 5=medium, 9=low; 0 is "no priority").

    `recurrence` requires `MS_TASKS_PLANNER_BETA=true`. To stop a
    series, pass `recurrence={"schedule": None}` — Graph's documented
    cancel form. The top-level `recurrence` cannot be set to None on a
    task that already has recurrence; Graph rejects that.
    """
    if not task_id or not task_id.strip():
        raise ValueError("planner_task_update requires a non-empty task_id")
    if status is not None and status not in _VALID_STATUS:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUS)} or None, got {status!r}")
    if priority is not None and not (0 <= priority <= 10):
        raise ValueError(f"priority must be 0..10 inclusive or None, got {priority}")

    if recurrence is not _UNSET:
        if not planner_beta_enabled():
            raise ValueError(
                "planner_task_update: `recurrence` requires "
                f"{PLANNER_BETA_ENV}=true (Microsoft Graph recurrence APIs are /beta-only)",
            )
        if recurrence is not None:
            validate_planner_recurrence(recurrence)

    task_id_s = task_id.strip()
    reg = registry if registry is not None else TaskRegistry(profile)
    entry = require_owned_by_profile(
        registry=reg,
        graph_id=task_id_s,
        expected_source="planner",
    )

    payload: dict[str, Any] = {}
    if title is not None:
        if not title.strip():
            raise ValueError("title, when given, must not be empty")
        payload["title"] = title.strip()
    if bucket_id is not None:
        if not bucket_id.strip():
            raise ValueError("bucket_id, when given, must not be empty")
        payload["bucketId"] = bucket_id.strip()
    if due_date is not None:
        payload["dueDateTime"] = due_date
    if status is not None:
        payload["percentComplete"] = 100 if status == "completed" else 0
    if priority is not None:
        payload["priority"] = priority
    if recurrence is not _UNSET:
        payload["recurrence"] = recurrence

    if not payload:
        raise ValueError(
            "planner_task_update requires at least one field to update "
            "(title / bucket_id / due_date / status / priority / recurrence)",
        )

    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    headers: dict[str, str] = {
        **auth_headers(token),
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    if entry.etag:
        headers["If-Match"] = entry.etag

    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.patch(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}",
            headers=headers,
            json=payload,
        )
        if response.status_code == 412:
            raise ExternallyModifiedError(task_id_s)
        response.raise_for_status()
        # With Prefer: return=representation, Graph returns the updated
        # entity. Some tenants still return 204 — fall back to a GET.
        if response.status_code == 204 or not response.content:
            get_response = client.get(
                f"{graph_planner_base()}/planner/tasks/{task_id_s}",
                headers=auth_headers(token),
            )
            get_response.raise_for_status()
            raw = get_response.json()
        else:
            raw = response.json()
        if not isinstance(raw, dict):
            raise ValueError("planner_task_update: Graph returned a non-object response")
        envelope = planner_envelope(raw, tenant_id=tenant_id)
    finally:
        if http is None:
            client.close()

    new_etag = envelope.get("etag") if isinstance(envelope.get("etag"), str) else None
    reg.update_etag(task_id_s, new_etag)
    return envelope
