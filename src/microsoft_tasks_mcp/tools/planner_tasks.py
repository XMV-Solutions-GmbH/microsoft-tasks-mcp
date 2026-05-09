# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_tasks — list tasks within a Planner plan (optionally narrowed
by bucket).

Wraps `GET /planner/plans/{planId}/tasks`. The optional `bucket_id`
narrows results client-side because Graph's bucket-tasks endpoint
doesn't support `$filter` reliably across all tenants.

Status filter is applied client-side (Planner uses `percentComplete`,
not a status enum, and Graph's `$filter` on percent-comparisons is
brittle).
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import (
    GRAPH_BASE,
    auth_headers,
    tenant_id_from_token,
)
from microsoft_tasks_mcp.tools._shape import planner_envelope

_VALID_STATUS_FILTERS = frozenset({"all", "completed", "not_completed"})


def list_planner_tasks(
    plan_id: str,
    *,
    bucket_id: str | None = None,
    status_filter: str = "all",
    limit: int = 100,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List Planner tasks in a plan.

    Returns each task in the unified envelope (see
    `_shape.planner_envelope`).
    """
    if not plan_id or not plan_id.strip():
        raise ValueError("planner_tasks requires a non-empty plan_id")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    if status_filter not in _VALID_STATUS_FILTERS:
        raise ValueError(
            f"status_filter must be one of {sorted(_VALID_STATUS_FILTERS)}, got {status_filter!r}",
        )

    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/planner/plans/{plan_id.strip()}/tasks",
            headers=auth_headers(token),
        )
        response.raise_for_status()
        return _extract_tasks(
            response.json(),
            bucket_id=bucket_id.strip() if bucket_id and bucket_id.strip() else None,
            status_filter=status_filter,
            limit=limit,
            tenant_id=tenant_id,
        )
    finally:
        if http is None:
            client.close()


def _extract_tasks(
    payload: dict[str, Any],
    *,
    bucket_id: str | None,
    status_filter: str,
    limit: int,
    tenant_id: str | None,
) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for task in raw:
        if len(out) >= limit:
            break
        if not isinstance(task, dict):
            continue
        if bucket_id is not None and task.get("bucketId") != bucket_id:
            continue
        envelope = planner_envelope(task, tenant_id=tenant_id)
        if status_filter == "completed" and envelope["status"] != "completed":
            continue
        if status_filter == "not_completed" and envelope["status"] != "not_completed":
            continue
        out.append(envelope)
    return out
