# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_task_update."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import (
    ExternallyModifiedError,
    NotOwnedByProfileError,
)
from microsoft_tasks_mcp.tools.planner_task_update import update_planner_task

URL = "https://graph.microsoft.com/v1.0/planner/tasks/T1"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_task_update.get_token",
        lambda profile: token,
    )


def _seed_registry(tmp_path: Path, etag: str | None = 'W/"old"') -> TaskRegistry:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(
        TaskEntry(
            source="planner",
            graph_id="T1",
            list_or_plan_id="P1",
            title="Old",
            etag=etag,
            created_at=0.0,
        )
    )
    return reg


@respx.mock
def test_updates_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.patch(URL).respond(
        json={
            "id": "T1",
            "title": "New",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"new"',
        }
    )
    out = update_planner_task("T1", title="New", registry=reg)
    assert out["title"] == "New"
    refreshed = reg.get("T1")
    assert refreshed is not None
    assert refreshed.etag == 'W/"new"'


@respx.mock
def test_passes_if_match_header(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path, etag='W/"v1"')
    route = respx.patch(URL).respond(
        json={
            "id": "T1",
            "title": "X",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"v2"',
        }
    )
    update_planner_task("T1", title="X", registry=reg)
    assert route.calls.last.request.headers["If-Match"] == 'W/"v1"'


@respx.mock
def test_412_raises_externally_modified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.patch(URL).respond(412, json={"error": "precondition"})
    with pytest.raises(ExternallyModifiedError):
        update_planner_task("T1", title="X", registry=reg)


def test_unowned_raises_before_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        update_planner_task("T1", title="X", registry=reg)


@respx.mock
def test_status_completed_maps_to_percent_100(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    route = respx.patch(URL).respond(
        json={
            "id": "T1",
            "planId": "P1",
            "percentComplete": 100,
            "assignments": {},
        }
    )
    update_planner_task("T1", status="completed", registry=reg)
    sent = route.calls.last.request.read().decode()
    assert '"percentComplete": 100' in sent or '"percentComplete":100' in sent


@respx.mock
def test_status_not_completed_maps_to_percent_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    route = respx.patch(URL).respond(
        json={
            "id": "T1",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
        }
    )
    update_planner_task("T1", status="not_completed", registry=reg)
    sent = route.calls.last.request.read().decode()
    assert '"percentComplete": 0' in sent or '"percentComplete":0' in sent


@respx.mock
def test_falls_back_to_get_when_204(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If Graph returns 204 (no body) ignoring our Prefer header, the
    tool must fall back to a GET to retrieve the updated state."""
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.patch(URL).respond(204)
    respx.get(URL).respond(
        json={
            "id": "T1",
            "title": "X-after",
            "planId": "P1",
            "percentComplete": 50,
            "assignments": {},
            "@odata.etag": 'W/"new"',
        }
    )
    out = update_planner_task("T1", title="X-after", registry=reg)
    assert out["title"] == "X-after"


def test_rejects_invalid_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with pytest.raises(ValueError, match="status must be"):
        update_planner_task("T1", status="urgent", registry=reg)


def test_rejects_priority_out_of_range(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with pytest.raises(ValueError, match=r"priority must be 0\.\.10"):
        update_planner_task("T1", priority=11, registry=reg)


def test_rejects_no_fields_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with pytest.raises(ValueError, match="at least one field"):
        update_planner_task("T1", registry=reg)


@respx.mock
def test_propagates_403(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.patch(URL).respond(403, json={"error": "no"})
    with pytest.raises(httpx.HTTPStatusError):
        update_planner_task("T1", title="X", registry=reg)


# ---------------------------------------------------------------------
# Recurrence (v0.4)
# ---------------------------------------------------------------------


_BETA_URL = "https://graph.microsoft.com/beta/planner/tasks/T1"


def test_recurrence_without_beta_flag_raises_before_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("MS_TASKS_PLANNER_BETA", raising=False)
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with pytest.raises(ValueError, match="MS_TASKS_PLANNER_BETA=true"):
        update_planner_task(
            "T1",
            recurrence={"schedule": {"pattern": {"type": "daily", "interval": 1}}},
            registry=reg,
        )


@respx.mock
def test_recurrence_set_routes_through_beta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MS_TASKS_PLANNER_BETA", "true")
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    route = respx.patch(_BETA_URL).respond(
        json={
            "id": "T1",
            "title": "X",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"v2"',
            "recurrence": {
                "seriesId": "S1",
                "occurrenceId": 2,
                "schedule": {
                    "pattern": {"type": "daily", "interval": 1},
                    "patternStartDateTime": "2026-05-09T08:00:00Z",
                },
            },
        }
    )
    out = update_planner_task(
        "T1",
        recurrence={
            "schedule": {
                "pattern": {"type": "daily", "interval": 1},
                "patternStartDateTime": "2026-05-09T08:00:00Z",
            },
        },
        registry=reg,
    )
    assert route.call_count == 1
    sent = route.calls.last.request.read().decode()
    assert '"recurrence"' in sent and '"daily"' in sent
    assert out["recurrence"]["seriesId"] == "S1"


@respx.mock
def test_recurrence_clear_via_schedule_null_forwards_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Per Graph: stop a series by setting recurrence.schedule = null."""
    monkeypatch.setenv("MS_TASKS_PLANNER_BETA", "true")
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    route = respx.patch(_BETA_URL).respond(
        json={
            "id": "T1",
            "title": "X",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"v2"',
            "recurrence": {"seriesId": "S1", "schedule": None, "occurrenceId": 1},
        }
    )
    update_planner_task(
        "T1",
        recurrence={"schedule": None},
        registry=reg,
    )
    sent = route.calls.last.request.read().decode()
    assert '"recurrence"' in sent and '"schedule":null' in sent


def test_recurrence_with_invalid_pattern_type_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MS_TASKS_PLANNER_BETA", "true")
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with pytest.raises(ValueError, match=r"pattern\.type must be one of"):
        update_planner_task(
            "T1",
            recurrence={"schedule": {"pattern": {"type": "hourly", "interval": 1}}},
            registry=reg,
        )


def test_omitted_recurrence_argument_does_not_send_recurrence_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The default `_UNSET` sentinel means recurrence stays out of the payload entirely.

    Important: passing `recurrence=None` is reserved for callers who want to *try*
    clearing top-level recurrence; that's a different intent than not touching it.
    """
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with respx.mock:
        respx.patch(URL).respond(
            json={
                "id": "T1",
                "title": "Y",
                "planId": "P1",
                "percentComplete": 0,
                "assignments": {},
                "@odata.etag": 'W/"v2"',
            }
        )
        update_planner_task("T1", title="Y", registry=reg)
        sent = respx.calls.last.request.read().decode()
    assert "recurrence" not in sent


# ---------------------------------------------------------------------
# v0.7 (#57) — TASKS_ALLOW_EXTERNAL_WRITES path
# ---------------------------------------------------------------------


@respx.mock
def test_external_write_fetches_fresh_etag_and_patches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """External-writes on + task not in registry: planner_task_update
    GETs the task first to learn @odata.etag, then PATCHes with that
    in If-Match. Planner tasks are addressable by id alone — no
    list_id parameter needed."""
    monkeypatch.setenv("TASKS_ALLOW_EXTERNAL_WRITES", "true")
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)  # empty

    respx.get(URL).respond(
        json={
            "id": "T1",
            "title": "External",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"external"',
        }
    )
    patch_route = respx.patch(URL).respond(
        json={
            "id": "T1",
            "title": "Updated",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"after"',
        }
    )

    out = update_planner_task("T1", title="Updated", registry=reg)
    assert out["title"] == "Updated"
    assert patch_route.calls.last.request.headers["If-Match"] == 'W/"external"'
    # Registry not polluted.
    assert reg.get("T1") is None


def test_external_write_flag_off_still_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without TASKS_ALLOW_EXTERNAL_WRITES, the registry guard fires
    even on a planner task — the flag is the only unlock."""
    monkeypatch.delenv("TASKS_ALLOW_EXTERNAL_WRITES", raising=False)
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        update_planner_task("T1", title="X", registry=reg)
