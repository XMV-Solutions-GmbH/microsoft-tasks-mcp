# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the shared write-tool guards."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import (
    ExternalListIdRequiredError,
    ExternallyModifiedError,
    NotOwnedByProfileError,
    require_owned_by_profile,
    validate_planner_recurrence,
)


def _entry(graph_id: str = "g1", source: Literal["todo", "planner"] = "todo") -> TaskEntry:
    return TaskEntry(
        source=source,
        graph_id=graph_id,
        list_or_plan_id="L1",
        title="T",
        etag='W/"e"',
        created_at=0.0,
    )


def test_require_owned_returns_entry_when_present(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    out = require_owned_by_profile(registry=reg, graph_id="g1", expected_source="todo")
    assert out is not None
    assert out.graph_id == "g1"


def test_require_owned_raises_when_missing(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError) as exc_info:
        require_owned_by_profile(registry=reg, graph_id="g999", expected_source="todo")
    assert "NOT_OWNED_BY_PROFILE" in str(exc_info.value)
    assert exc_info.value.graph_id == "g999"
    assert exc_info.value.source == "todo"


def test_require_owned_rejects_source_mismatch(tmp_path: Path) -> None:
    """A planner task in the registry must not pass a 'todo' guard."""
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1", source="planner"))
    with pytest.raises(NotOwnedByProfileError):
        require_owned_by_profile(registry=reg, graph_id="g1", expected_source="todo")


# ---------------------------------------------------------------------
# v0.7 (#57) — allow_external bypass
# ---------------------------------------------------------------------


def test_allow_external_returns_none_when_missing(tmp_path: Path) -> None:
    """With allow_external=True, a task not in the registry returns None
    rather than raising — the caller handles None by fetching a fresh
    ETag via GET and proceeding."""
    reg = TaskRegistry("default", base_dir=tmp_path)
    out = require_owned_by_profile(
        registry=reg,
        graph_id="g-external",
        expected_source="todo",
        allow_external=True,
    )
    assert out is None


def test_allow_external_returns_entry_when_present(tmp_path: Path) -> None:
    """A task IS in the registry — allow_external doesn't change the
    fast path, the entry is returned for cached list_id + etag reuse."""
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    out = require_owned_by_profile(
        registry=reg,
        graph_id="g1",
        expected_source="todo",
        allow_external=True,
    )
    assert out is not None
    assert out.graph_id == "g1"


def test_allow_external_still_rejects_source_mismatch(tmp_path: Path) -> None:
    """Source mismatch isn't an external-task scenario — it indicates
    a caller bug (planner code path called for a todo entry, or vice
    versa). Must still raise even with allow_external=True."""
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1", source="planner"))
    with pytest.raises(NotOwnedByProfileError):
        require_owned_by_profile(
            registry=reg,
            graph_id="g1",
            expected_source="todo",
            allow_external=True,
        )


def test_not_owned_error_message_mentions_external_writes_opt_in() -> None:
    """The NOT_OWNED_BY_PROFILE message must mention the opt-in env var
    so a naive agent can discover the unlock from the error alone
    (Phase B of the onboarding scenario in #57)."""
    err = NotOwnedByProfileError("todo", "g999")
    assert "TASKS_ALLOW_EXTERNAL_WRITES" in str(err)


def test_external_list_id_required_error_carries_graph_id() -> None:
    """The ExternalListIdRequiredError is the error a To Do write tool
    raises when the agent is acting on an external task but didn't
    pass list_id."""
    err = ExternalListIdRequiredError("g-external")
    assert "EXTERNAL_LIST_ID_REQUIRED" in str(err)
    assert err.graph_id == "g-external"
    assert "TASKS_ALLOW_EXTERNAL_WRITES" in str(err)
    assert "todo_lists" in str(err)


def test_externally_modified_error_message_carries_graph_id() -> None:
    err = ExternallyModifiedError("g1")
    assert "EXTERNALLY_MODIFIED" in str(err)
    assert err.graph_id == "g1"


# ---------------------------------------------------------------------
# validate_planner_recurrence — shape + enum guards
# ---------------------------------------------------------------------


def _good_weekly() -> dict[str, object]:
    return {
        "schedule": {
            "patternStartDateTime": "2026-05-09T08:00:00Z",
            "pattern": {
                "type": "weekly",
                "interval": 1,
                "daysOfWeek": ["monday"],
                "firstDayOfWeek": "sunday",
            },
        },
    }


def test_validate_recurrence_accepts_a_well_formed_weekly_payload() -> None:
    validate_planner_recurrence(_good_weekly())  # no exception


def test_validate_recurrence_accepts_schedule_null_for_cancellation() -> None:
    """Setting schedule to None is the documented Graph form to stop a series."""
    validate_planner_recurrence({"schedule": None})  # no exception


def test_validate_recurrence_rejects_non_dict_top_level() -> None:
    with pytest.raises(ValueError, match="recurrence must be a dict"):
        validate_planner_recurrence("weekly")


def test_validate_recurrence_requires_schedule_key() -> None:
    with pytest.raises(ValueError, match="must have a 'schedule' key"):
        validate_planner_recurrence({"foo": "bar"})


def test_validate_recurrence_rejects_non_dict_schedule_when_not_null() -> None:
    with pytest.raises(ValueError, match=r"schedule must be a dict or null"):
        validate_planner_recurrence({"schedule": "weekly"})


def test_validate_recurrence_requires_pattern_dict() -> None:
    with pytest.raises(ValueError, match="pattern must be a dict"):
        validate_planner_recurrence({"schedule": {"pattern": None}})


def test_validate_recurrence_rejects_unknown_pattern_type() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["type"] = "hourly"  # type: ignore[index]
    with pytest.raises(ValueError, match=r"pattern\.type must be one of"):
        validate_planner_recurrence(rec)


def test_validate_recurrence_rejects_zero_or_negative_interval() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["interval"] = 0  # type: ignore[index]
    with pytest.raises(ValueError, match="interval must be a positive int"):
        validate_planner_recurrence(rec)


def test_validate_recurrence_rejects_non_int_interval() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["interval"] = "1"  # type: ignore[index]
    with pytest.raises(ValueError, match="interval must be a positive int"):
        validate_planner_recurrence(rec)


def test_validate_recurrence_rejects_invalid_days_of_week() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["daysOfWeek"] = ["funday"]  # type: ignore[index]
    with pytest.raises(ValueError, match="daysOfWeek contains invalid day"):
        validate_planner_recurrence(rec)


def test_validate_recurrence_rejects_non_list_days_of_week() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["daysOfWeek"] = "monday"  # type: ignore[index]
    with pytest.raises(ValueError, match="daysOfWeek must be a list of strings"):
        validate_planner_recurrence(rec)


def test_validate_recurrence_rejects_invalid_first_day_of_week() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["firstDayOfWeek"] = "lunes"  # type: ignore[index]
    with pytest.raises(ValueError, match="firstDayOfWeek must be one of"):
        validate_planner_recurrence(rec)


def test_validate_recurrence_rejects_invalid_index() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["index"] = "fifth"  # type: ignore[index]
    with pytest.raises(ValueError, match="index must be one of"):
        validate_planner_recurrence(rec)


def test_validate_recurrence_accepts_valid_index() -> None:
    rec = _good_weekly()
    rec["schedule"]["pattern"]["type"] = "relativeMonthly"  # type: ignore[index]
    rec["schedule"]["pattern"]["index"] = "third"  # type: ignore[index]
    validate_planner_recurrence(rec)  # no exception


def test_validate_recurrence_accepts_daily_with_just_type_and_interval() -> None:
    """Per Graph docs, daily only requires type + interval."""
    validate_planner_recurrence({"schedule": {"pattern": {"type": "daily", "interval": 3}}})
