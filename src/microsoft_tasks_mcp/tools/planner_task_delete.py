# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_task_delete — delete a profile-owned Planner task.

DELETE /planner/tasks/{taskId} with `If-Match`. Idempotent: 404
treated as success.
"""

from __future__ import annotations

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers
from microsoft_tasks_mcp.tools._writes_common import require_owned_by_profile


def delete_planner_task(
    task_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> None:
    """Delete a Planner task this profile created.

    Refuses NOT_OWNED_BY_PROFILE if not in registry. Idempotent: a 404
    from Graph (already gone) is treated as success and the registry
    entry is cleaned up either way.
    """
    if not task_id or not task_id.strip():
        raise ValueError("planner_task_delete requires a non-empty task_id")

    task_id_s = task_id.strip()
    reg = registry if registry is not None else TaskRegistry(profile)
    entry = require_owned_by_profile(
        registry=reg,
        graph_id=task_id_s,
        expected_source="planner",
    )

    headers: dict[str, str] = auth_headers(get_token(profile))
    if entry.etag:
        headers["If-Match"] = entry.etag

    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.delete(
            f"{GRAPH_BASE}/planner/tasks/{task_id_s}",
            headers=headers,
        )
        if response.status_code == 404:
            reg.remove(task_id_s)
            return
        response.raise_for_status()
    finally:
        if http is None:
            client.close()

    reg.remove(task_id_s)
