# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_plan_get."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.planner_plan_get import get_planner_plan

URL_TMPL = "https://graph.microsoft.com/v1.0/planner/plans/{}"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_plan_get.get_token",
        lambda profile: token,
    )


@respx.mock
def test_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(
        json={
            "id": "p1",
            "title": "Sprint 5",
            "owner": "group-id-7",
            "createdDateTime": "2026-04-01T10:00:00Z",
            "@odata.etag": 'W/"e"',
        }
    )
    out = get_planner_plan("p1")
    assert out == {
        "id": "p1",
        "title": "Sprint 5",
        "owner_group_id": "group-id-7",
        "created_date_time": "2026-04-01T10:00:00Z",
        "etag": 'W/"e"',
    }


@respx.mock
def test_falls_back_to_container_id_when_owner_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(
        json={
            "id": "p1",
            "title": "X",
            "container": {"containerId": "c1", "type": "group"},
        }
    )
    out = get_planner_plan("p1")
    assert out["owner_group_id"] == "c1"


def test_rejects_empty_plan_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty plan_id"):
        get_planner_plan("")


@respx.mock
def test_propagates_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("missing")).respond(404, json={"error": "ItemNotFound"})
    with pytest.raises(httpx.HTTPStatusError):
        get_planner_plan("missing")
