# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_plan_get — fetch a single Microsoft Planner plan by id.

Wraps `GET /planner/plans/{planId}`. Read-only.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers


def get_planner_plan(
    plan_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch one Planner plan by id.

    Returns: `id`, `title`, `owner_group_id`, `created_date_time`,
    `etag`.
    """
    if not plan_id or not plan_id.strip():
        raise ValueError("planner_plan_get requires a non-empty plan_id")

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/planner/plans/{plan_id.strip()}",
            headers=auth_headers(token),
        )
        response.raise_for_status()
        return _extract_plan(response.json())
    finally:
        if http is None:
            client.close()


def _extract_plan(payload: dict[str, Any]) -> dict[str, Any]:
    container = payload.get("container")
    container_id = None
    if isinstance(container, dict):
        container_id = container.get("containerId")
    return {
        "id": payload.get("id"),
        "title": payload.get("title"),
        "owner_group_id": payload.get("owner") or container_id,
        "created_date_time": payload.get("createdDateTime"),
        "etag": payload.get("@odata.etag"),
    }
