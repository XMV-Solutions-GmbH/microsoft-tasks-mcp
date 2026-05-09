# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_task_get."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.planner_task_get import get_planner_task

TASK_URL_TMPL = "https://graph.microsoft.com/v1.0/planner/tasks/{}"
DETAILS_URL_TMPL = "https://graph.microsoft.com/v1.0/planner/tasks/{}/details"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_task_get.get_token",
        lambda profile: token,
    )


def _task(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "t1",
        "title": "Ship",
        "planId": "p1",
        "bucketId": "b1",
        "percentComplete": 50,
        "@odata.etag": 'W/"e"',
        "assignments": {},
    }
    base.update(overrides)
    return base


@respx.mock
def test_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASK_URL_TMPL.format("t1")).respond(json=_task())
    out = get_planner_task("t1")
    assert out["id"] == "t1"
    assert out["title"] == "Ship"
    assert out["status"] == "not_completed"
    assert out["plan_id"] == "p1"
    assert out["source"] == "planner"


def test_rejects_empty_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty task_id"):
        get_planner_task("")


@respx.mock
def test_propagates_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASK_URL_TMPL.format("missing")).respond(404, json={"error": "ItemNotFound"})
    with pytest.raises(httpx.HTTPStatusError):
        get_planner_task("missing")


@respx.mock
def test_include_details_folds_in_extra_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASK_URL_TMPL.format("t1")).respond(json=_task())
    respx.get(DETAILS_URL_TMPL.format("t1")).respond(
        json={
            "description": "Long description body.",
            "previewType": "automatic",
            "@odata.etag": 'W/"details-e"',
            "checklist": {
                "ck1": {"title": "Step 1", "isChecked": True, "orderHint": "8585"},
                "ck2": {"title": "Step 2", "isChecked": False, "orderHint": "8586"},
            },
            "references": {
                "https%3A//example.com": {
                    "alias": "Spec",
                    "type": "Other",
                }
            },
        }
    )
    out = get_planner_task("t1", include_details=True)
    assert out["description"] == "Long description body."
    assert out["preview_type"] == "automatic"
    assert out["details_etag"] == 'W/"details-e"'
    assert {item["id"] for item in out["checklist"]} == {"ck1", "ck2"}
    checked = next(item for item in out["checklist"] if item["id"] == "ck1")
    assert checked["is_checked"] is True
    assert checked["title"] == "Step 1"
    assert out["references"][0]["alias"] == "Spec"
    assert out["references"][0]["url"] == "https%3A//example.com"


@respx.mock
def test_include_details_handles_empty_subresources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASK_URL_TMPL.format("t1")).respond(json=_task())
    respx.get(DETAILS_URL_TMPL.format("t1")).respond(
        json={"description": "", "checklist": {}, "references": {}}
    )
    out = get_planner_task("t1", include_details=True)
    assert out["checklist"] == []
    assert out["references"] == []


@respx.mock
def test_include_details_propagates_details_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASK_URL_TMPL.format("t1")).respond(json=_task())
    respx.get(DETAILS_URL_TMPL.format("t1")).respond(403, json={"error": "no"})
    with pytest.raises(httpx.HTTPStatusError):
        get_planner_task("t1", include_details=True)


@respx.mock
def test_default_does_not_fetch_details(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    task_route = respx.get(TASK_URL_TMPL.format("t1")).respond(json=_task())
    details_route = respx.get(DETAILS_URL_TMPL.format("t1")).respond(json={})
    get_planner_task("t1")
    assert task_route.call_count == 1
    assert details_route.call_count == 0


@respx.mock
def test_rejects_non_object_task_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(TASK_URL_TMPL.format("t1")).respond(json=["not", "an", "object"])
    with pytest.raises(ValueError, match="non-object response"):
        get_planner_task("t1")
