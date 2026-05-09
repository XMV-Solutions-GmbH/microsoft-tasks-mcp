# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared task-shape helpers.

The MCP returns a unified "task" envelope across To Do and Planner so
agents don't have to learn two response shapes for what's conceptually
one entity. The envelope is documented in `docs/app-concept.md` § Tool
surface; this module is the canonical implementation.

Shape (always present):

- `id`: str
- `title`: str | None
- `status`: "completed" | "not_completed" | None
- `due_date`: ISO 8601 datetime str | None
- `assignees`: list[str] (UPNs / user-IDs; empty for To Do)
- `web_url`: str | None
- `source`: "todo" | "planner"
- `etag`: str | None  (ETag for write concurrency)

Source-specific extras live next to the envelope keys; helpers below
flatten Graph's nested representations into flat strings/lists.
"""

from __future__ import annotations

from typing import Any

# Microsoft To Do raw status values that count as "completed" for the
# unified envelope. Everything else (notStarted, inProgress,
# waitingOnOthers, deferred) maps to "not_completed".
_TODO_COMPLETED_STATUSES = frozenset({"completed"})


def normalise_todo_status(raw: Any) -> str | None:
    """Map Graph's To Do status enum to the unified two-state shape."""
    if not isinstance(raw, str):
        return None
    return "completed" if raw in _TODO_COMPLETED_STATUSES else "not_completed"


def normalise_planner_status(percent_complete: Any) -> str | None:
    """Planner uses percentComplete (0..100). Convention: 100 == completed."""
    try:
        pct = int(percent_complete)
    except (TypeError, ValueError):
        return None
    return "completed" if pct >= 100 else "not_completed"


def flatten_due_datetime(raw: Any) -> str | None:
    """Graph returns due dates as `{dateTime, timeZone}`; flatten to the
    ISO datetime string. Planner uses a flat ISO string already, so this
    helper is a no-op on those."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        candidate = raw.get("dateTime")
        return candidate if isinstance(candidate, str) else None
    return None


def todo_envelope(raw: dict[str, Any], *, list_id: str) -> dict[str, Any]:
    """Convert a Microsoft Graph To Do task payload into the unified
    task envelope plus To-Do-specific extras.

    Extras: `list_id`, `body_preview`, `categories`, `importance`,
    `reminder_date`, `is_reminder_on`, `last_modified_date_time`,
    `created_date_time`.
    """
    body = raw.get("body")
    body_preview: str | None = None
    if isinstance(body, dict):
        candidate = body.get("content")
        if isinstance(candidate, str):
            stripped = candidate.strip()
            body_preview = stripped[:200] if stripped else None

    categories = raw.get("categories")
    if not isinstance(categories, list):
        categories = []

    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "status": normalise_todo_status(raw.get("status")),
        "due_date": flatten_due_datetime(raw.get("dueDateTime")),
        "assignees": [],  # To Do is per-user; no assignee concept.
        "web_url": _build_todo_web_url(raw.get("id"), list_id),
        "source": "todo",
        "etag": raw.get("@odata.etag"),
        # Source-specific extras
        "list_id": list_id,
        "body_preview": body_preview,
        "categories": [c for c in categories if isinstance(c, str)],
        "importance": raw.get("importance"),
        "reminder_date": flatten_due_datetime(raw.get("reminderDateTime")),
        "is_reminder_on": bool(raw.get("isReminderOn", False)),
        "last_modified_date_time": raw.get("lastModifiedDateTime"),
        "created_date_time": raw.get("createdDateTime"),
    }


def _build_todo_web_url(task_id: Any, list_id: str) -> str | None:
    """To Do has no documented public deep-link URL pattern; the
    Microsoft web client uses an opaque path. Until that stabilises we
    return None and let the agent fall back to opening the To Do app
    by hand."""
    del task_id, list_id
    return None


def planner_envelope(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a Microsoft Graph Planner task payload into the unified
    task envelope plus Planner-specific extras.

    Extras: `plan_id`, `bucket_id`, `priority` (int), `percent_complete`
    (int 0..100), `body_preview` (None unless `details` were expanded),
    `created_date_time`, `last_modified_date_time`, `applied_categories`.
    """
    assignments = raw.get("assignments")
    assignees: list[str] = []
    if isinstance(assignments, dict):
        # Planner's assignments map is keyed by user-id; just collect
        # the keys (the values are assignee metadata, not the id).
        assignees = [k for k in assignments if isinstance(k, str)]

    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "status": normalise_planner_status(raw.get("percentComplete")),
        "due_date": flatten_due_datetime(raw.get("dueDateTime")),
        "assignees": assignees,
        "web_url": _build_planner_web_url(raw.get("id")),
        "source": "planner",
        "etag": raw.get("@odata.etag"),
        # Planner-specific extras
        "plan_id": raw.get("planId"),
        "bucket_id": raw.get("bucketId"),
        "priority": raw.get("priority"),
        "percent_complete": raw.get("percentComplete"),
        "applied_categories": _extract_applied_categories(raw.get("appliedCategories")),
        "created_date_time": raw.get("createdDateTime"),
        "last_modified_date_time": _last_modified_planner(raw),
    }


def _build_planner_web_url(task_id: Any) -> str | None:
    """Planner web URL pattern: tasks.office.com/{tenant}/Home/Task/{id}.

    The tenant segment varies per install — we'd need it threaded
    through from auth. For now return None and let the agent open
    Planner manually; a follow-up can wire the tenant in.
    """
    del task_id
    return None


def _extract_applied_categories(raw: Any) -> list[str]:
    """Planner's appliedCategories is a dict like
    {"category1": True, "category3": True}; flatten to a list of
    enabled category keys."""
    if not isinstance(raw, dict):
        return []
    return [key for key, value in raw.items() if isinstance(key, str) and value]


def _last_modified_planner(raw: dict[str, Any]) -> str | None:
    """Planner uses `lastModifiedDateTime` at the task level; also nests
    a `lastModifiedBy` complex object. We just want the timestamp."""
    candidate = raw.get("lastModifiedDateTime")
    return candidate if isinstance(candidate, str) else None
