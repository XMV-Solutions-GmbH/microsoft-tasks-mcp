# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_list_get — fetch a single Microsoft To Do list by id.

Wraps `GET /me/todo/lists/{listId}`. Read-only, idempotent.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers


def get_todo_list(
    list_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch one To Do list by id.

    Returns: `id`, `display_name`, `is_owner`, `is_shared`,
    `well_known_list_name`, `etag`.

    Raises:
        ValueError: empty list_id.
        httpx.HTTPStatusError: on a non-2xx response from Graph.
        microsoft_tasks_mcp.auth.AuthRequiredError: no usable cached
            token for `profile`.
    """
    if not list_id or not list_id.strip():
        raise ValueError("todo_list_get requires a non-empty list_id")

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me/todo/lists/{list_id.strip()}",
            headers=auth_headers(token),
        )
        response.raise_for_status()
        return _extract_list(response.json())
    finally:
        if http is None:
            client.close()


def _extract_list(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "display_name": payload.get("displayName"),
        "is_owner": bool(payload.get("isOwner", True)),
        "is_shared": bool(payload.get("isShared", False)),
        "well_known_list_name": payload.get("wellknownListName"),
        "etag": payload.get("@odata.etag"),
    }
