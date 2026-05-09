# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the unified-envelope shape helpers."""

from __future__ import annotations

from microsoft_tasks_mcp.tools._shape import planner_envelope, todo_envelope


def test_planner_envelope_web_url_none_when_tenant_missing() -> None:
    """v0.1/v0.2 default — without tenant_id the deep-link is None."""
    out = planner_envelope({"id": "T1", "title": "X", "percentComplete": 0})
    assert out["web_url"] is None


def test_planner_envelope_web_url_built_when_tenant_present() -> None:
    out = planner_envelope(
        {"id": "T1", "title": "X", "percentComplete": 0},
        tenant_id="11111111-2222-3333-4444-555555555555",
    )
    assert out["web_url"] == (
        "https://tasks.office.com/11111111-2222-3333-4444-555555555555/Home/Task/T1"
    )


def test_planner_envelope_web_url_none_when_id_missing() -> None:
    """Without an id we can't build a deep-link, even if tenant is set."""
    out = planner_envelope({"percentComplete": 0}, tenant_id="tenant-x")
    assert out["web_url"] is None


def test_planner_envelope_web_url_none_when_id_not_string() -> None:
    out = planner_envelope({"id": 12345, "percentComplete": 0}, tenant_id="tenant-x")
    assert out["web_url"] is None


def test_planner_envelope_web_url_none_when_tenant_empty_string() -> None:
    out = planner_envelope({"id": "T1", "percentComplete": 0}, tenant_id="")
    assert out["web_url"] is None


def test_todo_envelope_web_url_remains_none() -> None:
    """To Do has no documented stable public deep-link pattern; the
    envelope must keep returning None until that changes upstream."""
    out = todo_envelope({"id": "T1", "title": "X"}, list_id="L1")
    assert out["web_url"] is None


# ---------------------------------------------------------------------
# planner_envelope: recurrence passthrough (v0.4)
# ---------------------------------------------------------------------


def test_planner_envelope_recurrence_none_when_absent() -> None:
    out = planner_envelope({"id": "T1", "percentComplete": 0})
    assert out["recurrence"] is None


def test_planner_envelope_recurrence_none_when_not_dict() -> None:
    out = planner_envelope({"id": "T1", "recurrence": "weekly", "percentComplete": 0})
    assert out["recurrence"] is None


def test_planner_envelope_passes_through_full_recurrence_payload() -> None:
    raw = {
        "id": "T1",
        "percentComplete": 0,
        "recurrence": {
            "@odata.type": "#microsoft.graph.plannerTaskRecurrence",
            "seriesId": "series-abc",
            "occurrenceId": 3,
            "previousInSeriesTaskId": "T0",
            "nextInSeriesTaskId": "T2",
            "recurrenceStartDateTime": "2026-01-01T08:00:00Z",
            "schedule": {
                "patternStartDateTime": "2026-01-01T08:00:00Z",
                "nextOccurrenceDateTime": "2026-05-15T08:00:00Z",
                "pattern": {
                    "type": "weekly",
                    "interval": 1,
                    "daysOfWeek": ["monday"],
                    "firstDayOfWeek": "sunday",
                },
            },
        },
    }
    rec = planner_envelope(raw)["recurrence"]
    assert rec is not None
    assert rec["seriesId"] == "series-abc"
    assert rec["occurrenceId"] == 3
    assert rec["previousInSeriesTaskId"] == "T0"
    assert rec["nextInSeriesTaskId"] == "T2"
    assert rec["recurrenceStartDateTime"] == "2026-01-01T08:00:00Z"
    assert rec["schedule"]["patternStartDateTime"] == "2026-01-01T08:00:00Z"
    assert rec["schedule"]["nextOccurrenceDateTime"] == "2026-05-15T08:00:00Z"
    assert rec["schedule"]["pattern"]["type"] == "weekly"


def test_planner_envelope_handles_partial_recurrence_payload() -> None:
    """Defensive — Graph could conceivably omit some fields; we shouldn't crash."""
    raw = {
        "id": "T1",
        "percentComplete": 0,
        "recurrence": {"seriesId": "S1"},  # no schedule, no occurrenceId
    }
    rec = planner_envelope(raw)["recurrence"]
    assert rec == {
        "schedule": None,
        "seriesId": "S1",
        "occurrenceId": None,
        "previousInSeriesTaskId": None,
        "nextInSeriesTaskId": None,
        "recurrenceStartDateTime": None,
    }


def test_planner_envelope_recurrence_skips_pattern_when_not_dict() -> None:
    raw = {
        "id": "T1",
        "percentComplete": 0,
        "recurrence": {
            "schedule": {"pattern": "weekly", "patternStartDateTime": "2026-01-01T08:00:00Z"},
        },
    }
    rec = planner_envelope(raw)["recurrence"]
    assert rec is not None
    assert rec["schedule"]["pattern"] is None
    assert rec["schedule"]["patternStartDateTime"] == "2026-01-01T08:00:00Z"
