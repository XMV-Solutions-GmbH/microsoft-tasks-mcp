# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_plans — enumerate Microsoft Planner plans the user can see.

When called without `group_id`, lists plans across all M365 groups the
user is a member of. This requires the `Group.Read.All` delegated
scope (admin-consent — already granted tenant-wide on the XMV app).
With `group_id`, lists plans within that single group.

Microsoft Graph endpoints:
- GET /me/memberOf?$filter=... (M365-group enumeration)
- GET /groups/{id}/planner/plans (plans within a group)
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers, graph_planner_base


def list_planner_plans(
    *,
    group_id: str | None = None,
    limit: int = 50,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List Microsoft Planner plans visible to the signed-in user.

    Returns a list of plan envelopes (`id`, `title`, `owner_group_id`,
    `created_date_time`, `etag`).

    Without `group_id`, enumerates the user's M365 groups via
    `/me/memberOf`, then aggregates plans from each group up to
    `limit`. With `group_id`, fetches plans for that one group only.
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        if group_id and group_id.strip():
            return _list_plans_for_group(
                client=client,
                token=token,
                group_id=group_id.strip(),
                limit=limit,
            )
        return _list_plans_across_groups(client=client, token=token, limit=limit)
    finally:
        if http is None:
            client.close()


def _list_plans_for_group(
    *,
    client: httpx.Client,
    token: str,
    group_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    response = client.get(
        f"{graph_planner_base()}/groups/{group_id}/planner/plans",
        headers=auth_headers(token),
        params={"$top": limit},
    )
    response.raise_for_status()
    return _extract_plans(response.json())[:limit]


def _list_plans_across_groups(
    *,
    client: httpx.Client,
    token: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Enumerate the user's M365 groups, then fetch plans from each.

    Stops after collecting `limit` plans total. M365 groups are
    identified by `groupTypes` containing "Unified".
    """
    groups_response = client.get(
        f"{GRAPH_BASE}/me/memberOf",
        headers=auth_headers(token),
        params={"$top": 200, "$select": "id,groupTypes,displayName"},
    )
    groups_response.raise_for_status()
    groups_payload = groups_response.json()
    raw_groups = groups_payload.get("value", [])
    if not isinstance(raw_groups, list):
        return []

    plans: list[dict[str, Any]] = []
    for group in raw_groups:
        if len(plans) >= limit:
            break
        if not isinstance(group, dict):
            continue
        types = group.get("groupTypes")
        if not isinstance(types, list) or "Unified" not in types:
            continue  # only M365 groups have Planner plans
        gid = group.get("id")
        if not isinstance(gid, str):
            continue
        try:
            response = client.get(
                f"{graph_planner_base()}/groups/{gid}/planner/plans",
                headers=auth_headers(token),
                params={"$top": limit - len(plans)},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError:
            # 403 / 404 on a single group must not abort enumeration —
            # the user might be a member of a group whose Planner is
            # disabled or whose admin-consent for Planner.Read isn't
            # granted. Skip and continue.
            continue
        plans.extend(_extract_plans(response.json()))
    return plans[:limit]


def _extract_plans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for plan in raw:
        if not isinstance(plan, dict):
            continue
        out.append(
            {
                "id": plan.get("id"),
                "title": plan.get("title"),
                "owner_group_id": plan.get("owner") or plan.get("container", {}).get("containerId"),
                "created_date_time": plan.get("createdDateTime"),
                "etag": plan.get("@odata.etag"),
            }
        )
    return out
