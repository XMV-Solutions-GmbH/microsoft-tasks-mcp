# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_task_create."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools.planner_task_create import create_planner_task

POST_URL = "https://graph.microsoft.com/v1.0/planner/tasks"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_task_create.get_token",
        lambda profile: token,
    )


@respx.mock
def test_creates_task_returns_envelope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    respx.post(POST_URL).respond(
        201,
        json={
            "id": "T1",
            "title": "X",
            "planId": "P1",
            "bucketId": "B1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"e"',
        },
    )
    out = create_planner_task(
        "P1",
        "B1",
        "X",
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    assert out["id"] == "T1"
    assert out["plan_id"] == "P1"
    assert out["bucket_id"] == "B1"
    assert out["status"] == "not_completed"
    assert out["source"] == "planner"


@respx.mock
def test_adds_to_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    respx.post(POST_URL).respond(
        201,
        json={"id": "T1", "title": "X", "planId": "P1", "@odata.etag": 'W/"e"'},
    )
    create_planner_task("P1", "B1", "X", registry=reg)
    entry = reg.get("T1")
    assert entry is not None
    assert entry.source == "planner"
    assert entry.list_or_plan_id == "P1"


@respx.mock
def test_passes_assignees(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    route = respx.post(POST_URL).respond(201, json={"id": "T1", "title": "X", "planId": "P1"})
    create_planner_task(
        "P1",
        "B1",
        "X",
        assignees=["user-a", "user-b"],
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    sent = route.calls.last.request.read().decode()
    assert "user-a" in sent
    assert "user-b" in sent
    assert "plannerAssignment" in sent


@respx.mock
def test_passes_due_date(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    route = respx.post(POST_URL).respond(201, json={"id": "T1", "title": "X", "planId": "P1"})
    create_planner_task(
        "P1",
        "B1",
        "X",
        due_date="2026-12-31T00:00:00Z",
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    sent = route.calls.last.request.read().decode()
    assert "2026-12-31T00:00:00Z" in sent


@respx.mock
def test_with_body_writes_details(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    respx.post(POST_URL).respond(
        201,
        json={"id": "T1", "title": "X", "planId": "P1", "@odata.etag": 'W/"e"'},
    )
    respx.get("https://graph.microsoft.com/v1.0/planner/tasks/T1/details").respond(
        json={"@odata.etag": 'W/"d-e"'}
    )
    details_route = respx.patch(
        "https://graph.microsoft.com/v1.0/planner/tasks/T1/details"
    ).respond(204)
    out = create_planner_task(
        "P1",
        "B1",
        "X",
        body="long description",
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    assert out["description"] == "long description"
    assert details_route.call_count == 1
    sent = details_route.calls.last.request.read().decode()
    assert "long description" in sent
    assert details_route.calls.last.request.headers.get("If-Match") == 'W/"d-e"'


def test_rejects_empty_plan_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty plan_id"):
        create_planner_task("", "B1", "X", registry=TaskRegistry("default", base_dir=tmp_path))


def test_rejects_empty_bucket_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty bucket_id"):
        create_planner_task("P1", "", "X", registry=TaskRegistry("default", base_dir=tmp_path))


def test_rejects_empty_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty title"):
        create_planner_task("P1", "B1", "", registry=TaskRegistry("default", base_dir=tmp_path))


@respx.mock
def test_propagates_403(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    respx.post(POST_URL).respond(403, json={"error": "no"})
    with pytest.raises(httpx.HTTPStatusError):
        create_planner_task("P1", "B1", "X", registry=TaskRegistry("default", base_dir=tmp_path))


# ---------------------------------------------------------------------
# Recurrence (v0.4) — opt-in via MS_TASKS_PLANNER_BETA
# ---------------------------------------------------------------------


_BETA_POST_URL = "https://graph.microsoft.com/beta/planner/tasks"


def _good_weekly_recurrence() -> dict[str, object]:
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


def test_recurrence_without_beta_flag_raises_before_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("MS_TASKS_PLANNER_BETA", raising=False)
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="MS_TASKS_PLANNER_BETA=true"):
        create_planner_task(
            "P1",
            "B1",
            "X",
            recurrence=_good_weekly_recurrence(),
            registry=TaskRegistry("default", base_dir=tmp_path),
        )


@respx.mock
def test_recurrence_with_beta_flag_routes_through_beta_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MS_TASKS_PLANNER_BETA", "true")
    _patch_get_token(monkeypatch)
    route = respx.post(_BETA_POST_URL).respond(
        201,
        json={
            "id": "T1",
            "title": "X",
            "planId": "P1",
            "bucketId": "B1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"e"',
            "recurrence": {
                "seriesId": "S1",
                "occurrenceId": 1,
                "schedule": _good_weekly_recurrence()["schedule"],
            },
        },
    )
    out = create_planner_task(
        "P1",
        "B1",
        "X",
        recurrence=_good_weekly_recurrence(),
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    assert route.call_count == 1
    sent = route.calls.last.request.read().decode()
    assert '"recurrence"' in sent
    assert '"weekly"' in sent
    assert out["recurrence"] is not None
    assert out["recurrence"]["seriesId"] == "S1"


def test_recurrence_with_invalid_pattern_type_raises_before_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MS_TASKS_PLANNER_BETA", "true")
    _patch_get_token(monkeypatch)
    bad = _good_weekly_recurrence()
    bad["schedule"]["pattern"]["type"] = "hourly"  # type: ignore[index]
    with pytest.raises(ValueError, match=r"pattern\.type must be one of"):
        create_planner_task(
            "P1",
            "B1",
            "X",
            recurrence=bad,
            registry=TaskRegistry("default", base_dir=tmp_path),
        )
