# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_task_remove_reference."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import (
    ExternallyModifiedError,
    NotOwnedByProfileError,
)
from microsoft_tasks_mcp.tools.planner_task_remove_reference import (
    remove_planner_task_reference,
)

DETAILS_URL = "https://graph.microsoft.com/v1.0/planner/tasks/T1/details"
TASK_URL = "https://graph.microsoft.com/v1.0/planner/tasks/T1"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_task_remove_reference.get_token",
        lambda profile: token,
    )


def _seed_registry(tmp_path: Path) -> TaskRegistry:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(
        TaskEntry(
            source="planner",
            graph_id="T1",
            list_or_plan_id="P1",
            title="t",
            etag='W/"e"',
            created_at=0.0,
        )
    )
    return reg


def _stub_envelope_response() -> None:
    respx.get(TASK_URL).respond(
        json={
            "id": "T1",
            "title": "t",
            "planId": "P1",
            "percentComplete": 0,
            "assignments": {},
            "@odata.etag": 'W/"e"',
        }
    )


@respx.mock
def test_remove_reference_sends_null_value_patch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(
        json={
            "@odata.etag": 'W/"d"',
            "references": {"https%3A//example%2Ecom/x": {"alias": "Doc"}},
        }
    )
    patch_route = respx.patch(DETAILS_URL).respond(204)
    _stub_envelope_response()
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d2"', "references": {}})
    out = remove_planner_task_reference("T1", "https://example.com/x", registry=reg)
    sent = json.loads(patch_route.calls.last.request.read())
    assert sent == {"references": {"https%3A//example%2Ecom/x": None}}
    assert out["references"] == []


@respx.mock
def test_remove_reference_idempotent_on_missing_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Graph treats merge-with-null as a no-op for keys that don't exist;
    we should not raise."""
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"', "references": {}})
    respx.patch(DETAILS_URL).respond(204)
    _stub_envelope_response()
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d2"', "references": {}})
    out = remove_planner_task_reference("T1", "https://example.com/never-attached", registry=reg)
    assert out["references"] == []


@respx.mock
def test_remove_reference_translates_412(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"'})
    respx.patch(DETAILS_URL).respond(412)
    with pytest.raises(ExternallyModifiedError):
        remove_planner_task_reference("T1", "https://example.com/x", registry=reg)


def test_remove_reference_rejects_when_not_in_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    empty_reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        remove_planner_task_reference("T1", "https://example.com/x", registry=empty_reg)


def test_remove_reference_rejects_empty_task_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty task_id"):
        remove_planner_task_reference(
            "",
            "https://example.com/x",
            registry=TaskRegistry("default", base_dir=tmp_path),
        )


def test_remove_reference_rejects_non_http_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="http:// or https://"):
        remove_planner_task_reference(
            "T1",
            "ftp://example.com/file",
            registry=_seed_registry(tmp_path),
        )


@respx.mock
def test_remove_reference_keeps_other_refs_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The dictionary-merge means other references unchanged in the
    return envelope."""
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(
        json={
            "@odata.etag": 'W/"d"',
            "references": {
                "https%3A//example%2Ecom/x": {"alias": "Doc1"},
                "https%3A//example%2Ecom/y": {"alias": "Doc2"},
            },
        }
    )
    respx.patch(DETAILS_URL).respond(204)
    _stub_envelope_response()
    respx.get(DETAILS_URL).respond(
        json={
            "@odata.etag": 'W/"d2"',
            "references": {"https%3A//example%2Ecom/y": {"alias": "Doc2"}},
        }
    )
    out = remove_planner_task_reference("T1", "https://example.com/x", registry=reg)
    assert len(out["references"]) == 1
    assert out["references"][0]["url"] == "https://example.com/y"


@respx.mock
def test_remove_reference_propagates_500(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"'})
    respx.patch(DETAILS_URL).respond(500, json={"error": "server"})
    with pytest.raises(httpx.HTTPStatusError):
        remove_planner_task_reference("T1", "https://example.com/x", registry=reg)
