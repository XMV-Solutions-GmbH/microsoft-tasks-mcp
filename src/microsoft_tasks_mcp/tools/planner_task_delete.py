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
from microsoft_tasks_mcp.auth.flow import external_writes_enabled
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools._common import auth_headers, graph_planner_base
from microsoft_tasks_mcp.tools._writes_common import require_owned_by_profile


def delete_planner_task(
    task_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> None:
    """Delete a Planner task this profile created.

    Refuses NOT_OWNED_BY_PROFILE if not in registry AND
    `TASKS_ALLOW_EXTERNAL_WRITES` is unset/false. With external-writes
    on, tasks not in the registry are deletable too — `If-Match` is
    populated from a fresh GET so concurrent-write safety still
    applies. Idempotent: a 404 from Graph (already gone) is treated as
    success and the registry entry, if any, is cleaned up either way.
    """
    if not task_id or not task_id.strip():
        raise ValueError("planner_task_delete requires a non-empty task_id")

    task_id_s = task_id.strip()
    reg = registry if registry is not None else TaskRegistry(profile)
    allow_ext = external_writes_enabled()
    entry = require_owned_by_profile(
        registry=reg,
        graph_id=task_id_s,
        expected_source="planner",
        allow_external=allow_ext,
    )

    token = get_token(profile)
    headers: dict[str, str] = auth_headers(token)

    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        if entry is not None and entry.etag:
            headers["If-Match"] = entry.etag
        elif entry is None:
            # External-writes path: fetch current @odata.etag so the
            # delete still validates the read-before-write invariant.
            get_resp = client.get(
                f"{graph_planner_base()}/planner/tasks/{task_id_s}",
                headers=auth_headers(token),
            )
            if get_resp.status_code == 404:
                # Already gone — nothing to delete, nothing in registry.
                return
            get_resp.raise_for_status()
            get_payload = get_resp.json()
            if isinstance(get_payload, dict):
                fresh_etag = get_payload.get("@odata.etag")
                if isinstance(fresh_etag, str):
                    headers["If-Match"] = fresh_etag

        response = client.delete(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}",
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
