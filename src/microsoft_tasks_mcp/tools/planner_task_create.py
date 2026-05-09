# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_task_create — create a new Microsoft Planner task.

POST /planner/tasks. Adds the new task to this profile's registry so
the matching update / complete / delete tools can safely mutate it.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry, now
from microsoft_tasks_mcp.tools._common import (
    GRAPH_BASE,
    auth_headers,
    tenant_id_from_token,
)
from microsoft_tasks_mcp.tools._shape import planner_envelope


def create_planner_task(
    plan_id: str,
    bucket_id: str,
    title: str,
    *,
    body: str | None = None,
    due_date: str | None = None,
    assignees: list[str] | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Create a Planner task in `plan_id` / `bucket_id`.

    `assignees` is a list of M365 user-ids (NOT UPNs). The agent is
    only meant to populate this from values the user typed in chat —
    no auto-lookup of colleagues.

    Returns the unified envelope of the new task. Adds the new task's
    `graph_id` to this profile's registry. The `body` argument creates
    a `/details.description`; that requires a second Graph call which
    we make here (deferred from the agent's perspective — one tool
    call, two Graph round-trips).
    """
    if not plan_id or not plan_id.strip():
        raise ValueError("planner_task_create requires a non-empty plan_id")
    if not bucket_id or not bucket_id.strip():
        raise ValueError("planner_task_create requires a non-empty bucket_id")
    if not title or not title.strip():
        raise ValueError("planner_task_create requires a non-empty title")

    plan_id_s = plan_id.strip()
    bucket_id_s = bucket_id.strip()

    payload: dict[str, Any] = {
        "planId": plan_id_s,
        "bucketId": bucket_id_s,
        "title": title.strip(),
    }
    if due_date is not None:
        payload["dueDateTime"] = due_date
    if assignees:
        payload["assignments"] = {
            assignee_id: {
                "@odata.type": "#microsoft.graph.plannerAssignment",
                "orderHint": " !",
            }
            for assignee_id in assignees
            if isinstance(assignee_id, str) and assignee_id.strip()
        }

    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.post(
            f"{GRAPH_BASE}/planner/tasks",
            headers={**auth_headers(token), "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise ValueError("planner_task_create: Graph returned a non-object response")
        envelope = planner_envelope(raw, tenant_id=tenant_id)
        graph_id = envelope.get("id")

        # Optional body → write to /details
        if body is not None and isinstance(graph_id, str):
            # First fetch the freshly-created details to get its ETag.
            details_response = client.get(
                f"{GRAPH_BASE}/planner/tasks/{graph_id}/details",
                headers=auth_headers(token),
            )
            details_response.raise_for_status()
            details = details_response.json()
            details_etag = details.get("@odata.etag") if isinstance(details, dict) else None

            details_headers = {
                **auth_headers(token),
                "Content-Type": "application/json",
            }
            if isinstance(details_etag, str):
                details_headers["If-Match"] = details_etag

            patch_response = client.patch(
                f"{GRAPH_BASE}/planner/tasks/{graph_id}/details",
                headers=details_headers,
                json={"description": body},
            )
            patch_response.raise_for_status()
            envelope["description"] = body
    finally:
        if http is None:
            client.close()

    reg = registry if registry is not None else TaskRegistry(profile)
    if isinstance(graph_id, str):
        reg.add(
            TaskEntry(
                source="planner",
                graph_id=graph_id,
                list_or_plan_id=plan_id_s,
                title=envelope.get("title") or title.strip(),
                etag=envelope.get("etag"),
                created_at=now(),
            )
        )
    return envelope
