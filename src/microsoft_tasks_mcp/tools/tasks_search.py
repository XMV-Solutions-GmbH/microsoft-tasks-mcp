# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""tasks_search — client-side substring search across To Do + Planner.

Per `docs/app-concept.md` § Open tech-spike Q1: neither To Do nor
Planner expose a server-side `$search` for tasks. v0.1 implementation
is client-side: enumerate user's lists/plans, fetch tasks, filter by
case-insensitive substring against title + body_preview. Cap at
`limit` matches overall.

This is intentionally simple — at the typical task-volume scale
(100s of tasks per user, not 100k) it's fast enough. A spike on the
Microsoft Graph Search API (`/search/query`) is on the v0.2+ roadmap.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.auth.flow import planner_disabled
from microsoft_tasks_mcp.tools._common import (
    GRAPH_BASE,
    auth_headers,
    tenant_id_from_token,
)
from microsoft_tasks_mcp.tools._shape import planner_envelope, todo_envelope

_VALID_SOURCES = frozenset({"all", "todo", "planner"})


def search(
    query: str,
    *,
    source: str = "all",
    limit: int = 50,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Substring search across the user's To Do + Planner tasks.

    Case-insensitive match against `title` and `body_preview`. Returns
    up to `limit` matches in the unified envelope.
    """
    if not query or not query.strip():
        raise ValueError("tasks_search requires a non-empty query")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"source must be one of {sorted(_VALID_SOURCES)}, got {source!r}",
        )

    needle = query.strip().lower()
    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    planner_off = planner_disabled()
    try:
        out: list[dict[str, Any]] = []
        if source in ("all", "todo"):
            out.extend(_search_todo(client=client, token=token, needle=needle, limit=limit))
        if len(out) < limit and source in ("all", "planner") and not planner_off:
            out.extend(
                _search_planner(
                    client=client,
                    token=token,
                    tenant_id=tenant_id,
                    needle=needle,
                    limit=limit - len(out),
                )
            )
        return out[:limit]
    finally:
        if http is None:
            client.close()


def _search_todo(
    *,
    client: httpx.Client,
    token: str,
    needle: str,
    limit: int,
) -> list[dict[str, Any]]:
    lists_response = client.get(
        f"{GRAPH_BASE}/me/todo/lists",
        headers=auth_headers(token),
    )
    lists_response.raise_for_status()
    lists_payload = lists_response.json()
    raw_lists = lists_payload.get("value") if isinstance(lists_payload, dict) else None
    if not isinstance(raw_lists, list):
        return []

    out: list[dict[str, Any]] = []
    for entry in raw_lists:
        if len(out) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        list_id = entry.get("id")
        if not isinstance(list_id, str):
            continue
        try:
            tasks_response = client.get(
                f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks",
                headers=auth_headers(token),
                params={"$top": 200},
            )
            tasks_response.raise_for_status()
        except httpx.HTTPStatusError:
            continue
        tasks_payload = tasks_response.json()
        raw_tasks = tasks_payload.get("value") if isinstance(tasks_payload, dict) else None
        if not isinstance(raw_tasks, list):
            continue
        for task in raw_tasks:
            if len(out) >= limit:
                break
            if not isinstance(task, dict):
                continue
            envelope = todo_envelope(task, list_id=list_id)
            if _matches(envelope, needle):
                out.append(envelope)
    return out


def _search_planner(
    *,
    client: httpx.Client,
    token: str,
    tenant_id: str | None,
    needle: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Search Planner via /me/planner/tasks (assigned-to-me) — that's
    the closest the Planner API has to a per-user task feed; it's
    cheaper than enumerating every plan in every group.
    """
    try:
        response = client.get(
            f"{GRAPH_BASE}/me/planner/tasks",
            headers=auth_headers(token),
            params={"$top": 200},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError:
        return []
    payload = response.json()
    raw = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for task in raw:
        if len(out) >= limit:
            break
        if not isinstance(task, dict):
            continue
        envelope = planner_envelope(task, tenant_id=tenant_id)
        if _matches(envelope, needle):
            out.append(envelope)
    return out


def _matches(envelope: dict[str, Any], needle: str) -> bool:
    """Case-insensitive substring match against title + body_preview."""
    for field in ("title", "body_preview"):
        value = envelope.get(field)
        if isinstance(value, str) and needle in value.lower():
            return True
    return False
