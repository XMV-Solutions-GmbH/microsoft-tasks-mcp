# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""tasks_assigned_to_me — unified cross-source view of the user's tasks.

Per `docs/app-concept.md` § Open tech-spike Q2: there is no single
Microsoft Graph endpoint that returns "every task assigned to me
across both To Do and Planner". We make two calls:

- **Planner**: `GET /me/planner/tasks` — clean, returns every Planner
  task assigned to the current user.
- **To Do**: enumerate `/me/todo/lists`, then for each list
  `/me/todo/lists/{id}/tasks` (filtered server-side when possible).
  To Do is per-user and has no assignee concept, so "assigned to me"
  in the To Do half means "any of the user's tasks".

Both halves are merged client-side. Sorted by due_date ascending
(None last). Per-source cap is `limit // 2` so neither side starves
the other on large lists.

When `profiles=[...]` is supplied, the function fans out across each
profile (one signed-in tenant per profile name), tags each envelope
with its source `profile`, and merges. Per-profile failures are
best-effort skipped — the response includes a `_skipped_profiles`
key listing what didn't load and why. See
`docs/proposals/2026-05-09-cross-tenant-unified-view.md` for the
design rationale.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.auth.flow import planner_disabled
from microsoft_tasks_mcp.tools._common import (
    GRAPH_BASE,
    auth_headers,
    graph_planner_base,
    tenant_id_from_token,
)
from microsoft_tasks_mcp.tools._shape import planner_envelope, todo_envelope

_log = logging.getLogger(__name__)


def assigned_to_me(
    *,
    include_completed: bool = False,
    limit: int = 100,
    profile: str = "default",
    profiles: list[str] | None = None,
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return tasks currently assigned to the signed-in user across To
    Do + Planner.

    `include_completed=False` (default) excludes completed tasks from
    both surfaces. `limit` caps the merged result at that many entries
    overall, splitting the budget evenly across the two sources.

    `profiles=[...]` enables cross-tenant fan-out — see module docstring.
    When omitted, single-profile behaviour is preserved and `profile`
    is used.

    Returns a dict with two keys:

    - `tasks`: list of unified envelopes, each tagged with `profile`.
    - `_skipped_profiles`: list of `{profile, reason}` entries for any
      profile whose fetch failed; empty when everything succeeded.
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    target_profiles = list(profiles) if profiles else [profile]
    per_profile_limit = max(1, limit // max(1, len(target_profiles)))

    client = http if http is not None else httpx.Client(timeout=30.0)
    merged: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    try:
        for prof in target_profiles:
            try:
                merged.extend(
                    _fetch_one_profile(
                        client=client,
                        profile=prof,
                        include_completed=include_completed,
                        limit=per_profile_limit,
                    )
                )
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                # Best-effort: a profile whose token expired, whose
                # tenant returned 401/403, or whose Graph call timed
                # out should not abort the whole call. Log + continue.
                _log.warning("tasks_assigned_to_me skipping profile %r: %s", prof, exc)
                skipped.append({"profile": prof, "reason": str(exc)})
    finally:
        if http is None:
            client.close()

    merged.sort(key=_sort_key)
    return {"tasks": merged[:limit], "_skipped_profiles": skipped}


def _fetch_one_profile(
    *,
    client: httpx.Client,
    profile: str,
    include_completed: bool,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch the merged To Do + Planner result for a single profile,
    stamping each envelope with its `profile` for cross-tenant disambiguation.

    Per-source isolation: a Planner-half 4xx (e.g. 403 on a tenant
    without `Group.Read.All`) returns an empty Planner half but does
    NOT abort the To Do half. Conversely a To Do failure does not
    skip Planner. Only an unrecoverable error at the profile level
    (token fetch, etc.) bubbles up.
    """
    per_source = max(1, limit // 2)
    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    planner_tasks: list[dict[str, Any]] = []
    if not planner_disabled():
        try:
            planner_tasks = _fetch_planner(
                client=client,
                token=token,
                tenant_id=tenant_id,
                include_completed=include_completed,
                limit=per_source,
            )
        except httpx.HTTPStatusError:
            # Common in tenants where the user lacks Group.Read.All —
            # surface the To Do half rather than skipping the whole
            # profile.
            planner_tasks = []
    try:
        todo_tasks = _fetch_todo(
            client=client,
            token=token,
            include_completed=include_completed,
            limit=per_source,
        )
    except httpx.HTTPStatusError:
        todo_tasks = []
    out = todo_tasks + planner_tasks
    for envelope in out:
        envelope["profile"] = profile
    return out


def _fetch_planner(
    *,
    client: httpx.Client,
    token: str,
    tenant_id: str | None,
    include_completed: bool,
    limit: int,
) -> list[dict[str, Any]]:
    response = client.get(
        f"{graph_planner_base()}/me/planner/tasks",
        headers=auth_headers(token),
        params={"$top": limit * 2},  # over-fetch so post-filter still has signal
    )
    response.raise_for_status()
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
        if not include_completed and envelope["status"] == "completed":
            continue
        out.append(envelope)
    return out


def _fetch_todo(
    *,
    client: httpx.Client,
    token: str,
    include_completed: bool,
    limit: int,
) -> list[dict[str, Any]]:
    """Enumerate the user's To Do lists and pull tasks from each, up to
    `limit` total."""
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

        params: dict[str, str | int] = {"$top": max(1, limit - len(out))}
        if not include_completed:
            params["$filter"] = "status ne 'completed'"

        try:
            tasks_response = client.get(
                f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks",
                headers=auth_headers(token),
                params=params,
            )
            tasks_response.raise_for_status()
        except httpx.HTTPStatusError:
            # Skip lists where Graph returns 4xx (rare, e.g. shared
            # list whose owner revoked access mid-call).
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
            out.append(todo_envelope(task, list_id=list_id))
    return out


def _sort_key(task: dict[str, Any]) -> tuple[int, str]:
    """Sort by due_date ascending; entries with no due_date go last."""
    due = task.get("due_date")
    if isinstance(due, str) and due:
        return (0, due)
    return (1, "")
