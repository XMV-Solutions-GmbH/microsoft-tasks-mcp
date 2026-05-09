# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_lists — enumerate the signed-in user's Microsoft To Do lists.

Wraps `GET /me/todo/lists`. Read-only, idempotent.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers


def list_todo_lists(
    *,
    limit: int = 50,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List the user's To Do lists.

    Returns at most `limit` lists, each a dict with `id`,
    `display_name`, `is_owner`, `is_shared`, `well_known_list_name`
    (one of `defaultList`, `flaggedEmails`, `unknownFutureValue`, or
    None for user-created lists), and `etag`.

    Raises:
        ValueError: non-positive limit.
        httpx.HTTPStatusError: on a non-2xx response from Graph.
        microsoft_tasks_mcp.auth.AuthRequiredError: no usable cached
            token for `profile`.
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    params: dict[str, str | int] = {"$top": limit}

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me/todo/lists",
            headers=auth_headers(token),
            params=params,
        )
        response.raise_for_status()
        return _extract_lists(response.json())
    finally:
        if http is None:
            client.close()


def _extract_lists(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "id": entry.get("id"),
                "display_name": entry.get("displayName"),
                "is_owner": bool(entry.get("isOwner", True)),
                "is_shared": bool(entry.get("isShared", False)),
                "well_known_list_name": entry.get("wellknownListName"),
                "etag": entry.get("@odata.etag"),
            }
        )
    return out
