# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_task_add_reference."""

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
from microsoft_tasks_mcp.tools.planner_task_add_reference import add_planner_task_reference

DETAILS_URL = "https://graph.microsoft.com/v1.0/planner/tasks/T1/details"
TASK_URL = "https://graph.microsoft.com/v1.0/planner/tasks/T1"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_task_add_reference.get_token",
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


def _stub_envelope_responses() -> None:
    """Boilerplate happy-path GET stubs the tool fires after the PATCH."""
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
def test_add_reference_sends_patch_to_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"', "references": {}})
    patch_route = respx.patch(DETAILS_URL).respond(204)
    _stub_envelope_responses()
    # post-patch details GET — what shows the new reference present
    respx.get(DETAILS_URL).respond(
        json={
            "@odata.etag": 'W/"d2"',
            "references": {
                "https%3A//example%2Ecom/x": {
                    "alias": "Doc",
                    "type": "Word",
                },
            },
        }
    )
    out = add_planner_task_reference(
        "T1",
        "https://example.com/x",
        alias="Doc",
        type_hint="Word",
        registry=reg,
    )
    assert patch_route.call_count == 1
    sent = json.loads(patch_route.calls.last.request.read())
    assert sent["references"] == {
        "https%3A//example%2Ecom/x": {
            "@odata.type": "#microsoft.graph.plannerExternalReference",
            "alias": "Doc",
            "type": "Word",
        },
    }
    assert out["references"][0]["url"] == "https://example.com/x"
    assert out["references"][0]["alias"] == "Doc"
    assert out["references"][0]["type"] == "Word"


@respx.mock
def test_add_reference_passes_if_match_header(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    # Sequence the two GET /details calls: pre-patch returns d-old (which
    # must show up in the PATCH's If-Match), post-patch returns d-new.
    respx.get(DETAILS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"@odata.etag": 'W/"d-old"', "references": {}}),
            httpx.Response(200, json={"@odata.etag": 'W/"d-new"', "references": {}}),
        ]
    )
    patch_route = respx.patch(DETAILS_URL).respond(204)
    _stub_envelope_responses()
    add_planner_task_reference("T1", "https://example.com/x", registry=reg)
    assert patch_route.calls.last.request.headers.get("If-Match") == 'W/"d-old"'


@respx.mock
def test_add_reference_translates_412_to_externally_modified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"'})
    respx.patch(DETAILS_URL).respond(412)
    with pytest.raises(ExternallyModifiedError):
        add_planner_task_reference("T1", "https://example.com/x", registry=reg)


def test_add_reference_rejects_when_not_in_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    empty_reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        add_planner_task_reference("T1", "https://example.com/x", registry=empty_reg)


def test_add_reference_rejects_empty_task_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty task_id"):
        add_planner_task_reference(
            "",
            "https://example.com/x",
            registry=TaskRegistry("default", base_dir=tmp_path),
        )


def test_add_reference_rejects_non_http_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="http:// or https://"):
        add_planner_task_reference(
            "T1",
            "onenote:https://example.com/x",
            registry=_seed_registry(tmp_path),
        )


def test_add_reference_rejects_empty_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="must not be empty"):
        add_planner_task_reference(
            "T1",
            "",
            registry=_seed_registry(tmp_path),
        )


def test_add_reference_registry_guard_runs_before_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even with a respx mock that would 200, the registry guard must
    fire first — proving the tool layer is the gate, not Graph."""
    _patch_get_token(monkeypatch)
    empty_reg = TaskRegistry("default", base_dir=tmp_path)
    with respx.mock:
        # If the guard is bypassed, this stub would be hit and the test
        # would fail by NOT raising NotOwnedByProfileError.
        respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"'})
        respx.patch(DETAILS_URL).respond(204)
        with pytest.raises(NotOwnedByProfileError):
            add_planner_task_reference("T1", "https://example.com/x", registry=empty_reg)


@respx.mock
def test_add_reference_propagates_503(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"'})
    respx.patch(DETAILS_URL).respond(503, json={"error": "server"})
    with pytest.raises(httpx.HTTPStatusError):
        add_planner_task_reference("T1", "https://example.com/x", registry=reg)


@respx.mock
def test_add_reference_omits_alias_and_type_when_not_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d"', "references": {}})
    patch_route = respx.patch(DETAILS_URL).respond(204)
    _stub_envelope_responses()
    respx.get(DETAILS_URL).respond(json={"@odata.etag": 'W/"d2"', "references": {}})
    add_planner_task_reference("T1", "https://example.com/x", registry=reg)
    sent_entry = json.loads(patch_route.calls.last.request.read())["references"][
        "https%3A//example%2Ecom/x"
    ]
    assert "alias" not in sent_entry
    assert "type" not in sent_entry
    assert sent_entry["@odata.type"] == "#microsoft.graph.plannerExternalReference"
