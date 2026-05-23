# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared error types + helpers for the v0.2 write tools.

The load-bearing safety check — `require_owned_by_profile` — is the
gate every mutating tool runs *before* it makes any Microsoft Graph
call. If the task isn't in this profile's registry, the tool raises
`NotOwnedByProfileError` and never touches Graph.
"""

from __future__ import annotations

from typing import Any

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry

# Microsoft Graph `recurrencePattern` enum values — shared across
# Planner (and, in a follow-up issue, To Do). Validation is deliberately
# thin: we catch obviously-wrong enum values before the HTTP call so the
# agent gets a clear local error, but we don't replicate the full
# "type X requires fields Y and Z" matrix because Graph is the
# authoritative source for that and its error message is more useful
# than ours would be after drift.
_VALID_PATTERN_TYPES = frozenset(
    {"daily", "weekly", "absoluteMonthly", "relativeMonthly", "absoluteYearly", "relativeYearly"},
)
_VALID_DAYS_OF_WEEK = frozenset(
    {"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"},
)
_VALID_INDEX = frozenset({"first", "second", "third", "fourth", "last"})


def validate_planner_recurrence(recurrence: Any) -> None:
    """Validate a Planner `recurrence` argument shape before HTTP.

    `recurrence` must be a dict with a `schedule` containing a `pattern`
    that has `type` (in `_VALID_PATTERN_TYPES`) and `interval` (int).
    `daysOfWeek`, `firstDayOfWeek`, and `index` enums are checked when
    present; everything else is passed through to Graph for validation.

    Permitting `recurrence={"schedule": None}` is intentional — that's
    how a series is discontinued per Graph semantics. The top-level
    `recurrence` itself cannot be set to None on a task that already
    has recurrence (Graph rejects that); we don't pre-empt that error
    locally, we let Graph surface it.

    Raises `ValueError` on shape errors. Returns None on success.
    """
    if not isinstance(recurrence, dict):
        raise ValueError("recurrence must be a dict")
    if "schedule" not in recurrence:
        raise ValueError("recurrence must have a 'schedule' key")
    schedule = recurrence["schedule"]
    if schedule is None:
        return  # cancellation form
    if not isinstance(schedule, dict):
        raise ValueError("recurrence.schedule must be a dict or null")
    pattern = schedule.get("pattern")
    if not isinstance(pattern, dict):
        raise ValueError("recurrence.schedule.pattern must be a dict")
    pat_type = pattern.get("type")
    if pat_type not in _VALID_PATTERN_TYPES:
        raise ValueError(
            f"recurrence.schedule.pattern.type must be one of {sorted(_VALID_PATTERN_TYPES)}, "
            f"got {pat_type!r}",
        )
    interval = pattern.get("interval")
    if not isinstance(interval, int) or interval < 1:
        raise ValueError(
            f"recurrence.schedule.pattern.interval must be a positive int, got {interval!r}",
        )
    days = pattern.get("daysOfWeek")
    if days is not None:
        if not isinstance(days, list) or not all(isinstance(d, str) for d in days):
            raise ValueError("recurrence.schedule.pattern.daysOfWeek must be a list of strings")
        bad = [d for d in days if d not in _VALID_DAYS_OF_WEEK]
        if bad:
            raise ValueError(
                f"recurrence.schedule.pattern.daysOfWeek contains invalid day(s) {bad}; "
                f"valid: {sorted(_VALID_DAYS_OF_WEEK)}",
            )
    fdow = pattern.get("firstDayOfWeek")
    if fdow is not None and fdow not in _VALID_DAYS_OF_WEEK:
        raise ValueError(
            f"recurrence.schedule.pattern.firstDayOfWeek must be one of "
            f"{sorted(_VALID_DAYS_OF_WEEK)}, got {fdow!r}",
        )
    index = pattern.get("index")
    if index is not None and index not in _VALID_INDEX:
        raise ValueError(
            f"recurrence.schedule.pattern.index must be one of {sorted(_VALID_INDEX)}, "
            f"got {index!r}",
        )


class ExternalListIdRequiredError(ValueError):
    """Raised by a To Do write tool when external-writes is enabled and
    the caller is acting on a task that isn't in the profile's
    registry, but didn't pass the `list_id` argument the tool needs to
    construct the `/me/todo/lists/{listId}/tasks/{taskId}` URL.

    Microsoft Graph's To Do API has no `/me/todo/tasks/{taskId}` shape —
    tasks are addressable only via their containing list. For tasks
    this MCP profile created, the list_id lives in the registry; for
    external tasks under the `TASKS_ALLOW_EXTERNAL_WRITES=true` path
    the agent must supply it explicitly.

    Planner tools never raise this — Planner tasks are addressable by
    id alone (`/planner/tasks/{taskId}`).
    """

    def __init__(self, graph_id: str) -> None:
        super().__init__(
            f"EXTERNAL_LIST_ID_REQUIRED: task {graph_id!r} is not in this "
            "MCP profile's registry. With TASKS_ALLOW_EXTERNAL_WRITES=true "
            "you may act on tasks created elsewhere, but you must pass "
            "the `list_id` argument so the tool can address the task on "
            "Microsoft Graph. Discover list ids via the `todo_lists` tool.",
        )
        self.graph_id = graph_id


class NotOwnedByProfileError(RuntimeError):
    """Raised when a write tool is asked to act on a task that this
    profile's registry doesn't track.

    Surfaces to the agent as a clear error rather than silently
    succeeding (Graph would happily mutate any task the user has
    permission for; this guard is what makes "agent never modifies
    tasks created by humans or other agents" load-bearing).
    """

    def __init__(self, source: str, graph_id: str) -> None:
        super().__init__(
            f"NOT_OWNED_BY_PROFILE: task {graph_id!r} (source={source!r}) "
            "is not in this MCP profile's created-by-me registry. The "
            "MCP server refuses to update / complete / delete tasks "
            "it did not create itself. To opt the operator into "
            "letting this MCP server act on externally-created tasks "
            "too (e.g. tasks typed manually in the Microsoft To Do app "
            "by the same user), set TASKS_ALLOW_EXTERNAL_WRITES=true "
            "in the MCP client config. Default behaviour (this error) "
            "is the safer choice for shared / multi-author setups.",
        )
        self.source = source
        self.graph_id = graph_id


class ExternallyModifiedError(RuntimeError):
    """Raised when Microsoft Graph rejects a write because the task's
    ETag changed externally between the agent's read and write.

    Surfaces as `EXTERNALLY_MODIFIED` so the agent can re-fetch and
    decide whether to retry with the new state."""

    def __init__(self, graph_id: str) -> None:
        super().__init__(
            f"EXTERNALLY_MODIFIED: task {graph_id!r} was modified "
            "externally between read and write. Re-fetch via the "
            "matching `_task_get` tool and decide whether to retry.",
        )
        self.graph_id = graph_id


def require_owned_by_profile(
    *,
    registry: TaskRegistry,
    graph_id: str,
    expected_source: str,
    allow_external: bool = False,
) -> TaskEntry | None:
    """Look up `graph_id` in the registry and gate by ownership.

    Default mode (`allow_external=False`): raises `NotOwnedByProfileError`
    if the task isn't in the registry or has the wrong source. Returns
    the entry on success. This is the load-bearing safety guard that
    makes "agent never modifies tasks created by humans or other agents"
    true.

    External-writes mode (`allow_external=True`, enabled via
    `TASKS_ALLOW_EXTERNAL_WRITES=true`; #57): returns the entry if
    present, or `None` if the task isn't in the registry. The caller
    is responsible for fetching the current ETag from Graph and
    threading it through `If-Match` — the EXTERNALLY_MODIFIED guard
    still applies, only the ownership-by-this-MCP guard is relaxed.

    A registry entry with the WRONG source (e.g. a `planner` task in
    the To Do code path) is still rejected even with `allow_external`,
    because that mismatch indicates a caller bug, not an external task.
    """
    entry = registry.get(graph_id)
    if entry is None:
        if allow_external:
            return None
        raise NotOwnedByProfileError(expected_source, graph_id)
    if entry.source != expected_source:
        raise NotOwnedByProfileError(expected_source, graph_id)
    return entry
