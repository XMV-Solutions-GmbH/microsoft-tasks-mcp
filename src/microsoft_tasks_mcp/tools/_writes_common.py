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
            "it did not create itself.",
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
) -> TaskEntry:
    """Raise `NotOwnedByProfileError` if `graph_id` isn't in the registry.

    Returns the existing entry on success. Used by every write tool
    before it makes any Microsoft Graph call — the guard is at the
    tool layer, not at Graph, so even a mis-scoped attempt is caught.
    """
    entry = registry.get(graph_id)
    if entry is None or entry.source != expected_source:
        raise NotOwnedByProfileError(expected_source, graph_id)
    return entry
