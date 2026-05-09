# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_buckets — list buckets within a Planner plan.

Wraps `GET /planner/plans/{planId}/buckets`. Read-only.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers


def list_planner_buckets(
    plan_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List buckets within a Planner plan.

    Returns each bucket as `id`, `name`, `plan_id`, `order_hint`,
    `etag`.
    """
    if not plan_id or not plan_id.strip():
        raise ValueError("planner_buckets requires a non-empty plan_id")

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/planner/plans/{plan_id.strip()}/buckets",
            headers=auth_headers(token),
        )
        response.raise_for_status()
        return _extract_buckets(response.json())
    finally:
        if http is None:
            client.close()


def _extract_buckets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for bucket in raw:
        if not isinstance(bucket, dict):
            continue
        out.append(
            {
                "id": bucket.get("id"),
                "name": bucket.get("name"),
                "plan_id": bucket.get("planId"),
                "order_hint": bucket.get("orderHint"),
                "etag": bucket.get("@odata.etag"),
            }
        )
    return out
