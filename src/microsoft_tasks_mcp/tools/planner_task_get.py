# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_task_get — fetch a single Planner task by id.

Wraps `GET /planner/tasks/{taskId}` plus optional
`GET /planner/tasks/{taskId}/details` when `include_details=True`.

Read-only.
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


def get_planner_task(
    task_id: str,
    *,
    include_details: bool = False,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch one Planner task by id.

    Returns the unified task envelope. When `include_details=True`,
    additionally fetches `/details` and folds in:

    - `description` (free-form body, str | None)
    - `checklist` (list of `{id, title, is_checked, order_hint}`)
    - `references` (list of `{url, alias, type}`)
    - `preview_type` (str | None)
    - `details_etag` (str | None — for write concurrency on the details
      sub-resource, separate from the task ETag)
    """
    if not task_id or not task_id.strip():
        raise ValueError("planner_task_get requires a non-empty task_id")

    task_id_s = task_id.strip()
    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/planner/tasks/{task_id_s}",
            headers=auth_headers(token),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("planner_task_get: Graph returned a non-object response")
        envelope = planner_envelope(payload, tenant_id=tenant_id)

        if include_details:
            details_response = client.get(
                f"{GRAPH_BASE}/planner/tasks/{task_id_s}/details",
                headers=auth_headers(token),
            )
            details_response.raise_for_status()
            details = details_response.json()
            if isinstance(details, dict):
                envelope["description"] = details.get("description")
                envelope["preview_type"] = details.get("previewType")
                envelope["details_etag"] = details.get("@odata.etag")
                envelope["checklist"] = _extract_checklist(details.get("checklist"))
                envelope["references"] = _extract_references(details.get("references"))

        return envelope
    finally:
        if http is None:
            client.close()


def _extract_checklist(raw: Any) -> list[dict[str, Any]]:
    """Planner checklist is a dict keyed by id, where each value is
    `{title, isChecked, orderHint, lastModifiedBy, lastModifiedDateTime}`.
    Flatten to a list of `{id, title, is_checked, order_hint}`.
    """
    if not isinstance(raw, dict):
        return []
    out: list[dict[str, Any]] = []
    for item_id, value in raw.items():
        if not isinstance(item_id, str) or not isinstance(value, dict):
            continue
        out.append(
            {
                "id": item_id,
                "title": value.get("title"),
                "is_checked": bool(value.get("isChecked", False)),
                "order_hint": value.get("orderHint"),
            }
        )
    return out


def _extract_references(raw: Any) -> list[dict[str, Any]]:
    """Planner references is a dict keyed by URL-encoded URL, with
    `{alias, type, lastModifiedBy, lastModifiedDateTime}` values.
    Flatten to a list of `{url, alias, type}`.
    """
    if not isinstance(raw, dict):
        return []
    out: list[dict[str, Any]] = []
    for url_key, value in raw.items():
        if not isinstance(url_key, str) or not isinstance(value, dict):
            continue
        out.append(
            {
                "url": url_key,
                "alias": value.get("alias"),
                "type": value.get("type"),
            }
        )
    return out
