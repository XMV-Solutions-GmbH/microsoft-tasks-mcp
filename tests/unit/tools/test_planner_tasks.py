# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_tasks."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.planner_tasks import list_planner_tasks

URL_TMPL = "https://graph.microsoft.com/v1.0/planner/plans/{}/tasks"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_tasks.get_token",
        lambda profile: token,
    )


def _task(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "t1",
        "title": "Ship it",
        "planId": "p1",
        "bucketId": "b1",
        "percentComplete": 0,
        "priority": 5,
        "assignments": {"user-1": {"orderHint": "8585"}},
        "createdDateTime": "2026-04-01T10:00:00Z",
        "lastModifiedDateTime": "2026-04-02T10:00:00Z",
        "dueDateTime": "2026-05-01T00:00:00Z",
        "@odata.etag": 'W/"e"',
    }
    base.update(overrides)
    return base


@respx.mock
def test_returns_unified_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(json={"value": [_task()]})
    out = list_planner_tasks("p1")
    assert len(out) == 1
    task = out[0]
    assert task["id"] == "t1"
    assert task["source"] == "planner"
    assert task["status"] == "not_completed"
    assert task["assignees"] == ["user-1"]
    assert task["plan_id"] == "p1"
    assert task["bucket_id"] == "b1"
    assert task["priority"] == 5
    assert task["percent_complete"] == 0
    assert task["due_date"] == "2026-05-01T00:00:00Z"
    assert task["etag"] == 'W/"e"'


@respx.mock
def test_percent_complete_100_maps_to_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(json={"value": [_task(percentComplete=100)]})
    assert list_planner_tasks("p1")[0]["status"] == "completed"


@respx.mock
def test_percent_complete_50_maps_to_not_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(json={"value": [_task(percentComplete=50)]})
    assert list_planner_tasks("p1")[0]["status"] == "not_completed"


@respx.mock
def test_bucket_id_filter_narrows_client_side(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(
        json={
            "value": [
                _task(id="t1", bucketId="b1"),
                _task(id="t2", bucketId="b2"),
                _task(id="t3", bucketId="b1"),
            ]
        }
    )
    out = list_planner_tasks("p1", bucket_id="b1")
    assert {t["id"] for t in out} == {"t1", "t3"}


@respx.mock
def test_status_filter_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(
        json={
            "value": [
                _task(id="t1", percentComplete=0),
                _task(id="t2", percentComplete=100),
                _task(id="t3", percentComplete=100),
            ]
        }
    )
    out = list_planner_tasks("p1", status_filter="completed")
    assert {t["id"] for t in out} == {"t2", "t3"}


@respx.mock
def test_status_filter_not_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(
        json={
            "value": [
                _task(id="t1", percentComplete=0),
                _task(id="t2", percentComplete=100),
            ]
        }
    )
    out = list_planner_tasks("p1", status_filter="not_completed")
    assert [t["id"] for t in out] == ["t1"]


@respx.mock
def test_limit_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(json={"value": [_task(id=f"t{i}") for i in range(10)]})
    out = list_planner_tasks("p1", limit=3)
    assert len(out) == 3


@respx.mock
def test_assignments_missing_yields_empty_assignees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    payload = _task()
    del payload["assignments"]
    respx.get(URL_TMPL.format("p1")).respond(json={"value": [payload]})
    assert list_planner_tasks("p1")[0]["assignees"] == []


def test_rejects_empty_plan_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty plan_id"):
        list_planner_tasks("")


def test_rejects_invalid_status_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="status_filter must be"):
        list_planner_tasks("p1", status_filter="urgent")


def test_rejects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        list_planner_tasks("p1", limit=0)


@respx.mock
def test_propagates_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(404, json={"error": "missing"})
    with pytest.raises(httpx.HTTPStatusError):
        list_planner_tasks("p1")
