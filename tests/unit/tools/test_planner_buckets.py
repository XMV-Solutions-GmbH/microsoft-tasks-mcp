# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_buckets."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.planner_buckets import list_planner_buckets

URL_TMPL = "https://graph.microsoft.com/v1.0/planner/plans/{}/buckets"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_buckets.get_token",
        lambda profile: token,
    )


@respx.mock
def test_returns_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(
        json={
            "value": [
                {
                    "id": "b1",
                    "name": "Todo",
                    "planId": "p1",
                    "orderHint": "8585",
                    "@odata.etag": 'W/"e1"',
                },
                {
                    "id": "b2",
                    "name": "Done",
                    "planId": "p1",
                    "orderHint": "8586",
                    "@odata.etag": 'W/"e2"',
                },
            ]
        }
    )
    out = list_planner_buckets("p1")
    assert len(out) == 2
    assert out[0]["name"] == "Todo"
    assert out[0]["plan_id"] == "p1"
    assert out[0]["order_hint"] == "8585"
    assert out[0]["etag"] == 'W/"e1"'


def test_rejects_empty_plan_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty plan_id"):
        list_planner_buckets("")


@respx.mock
def test_skips_non_dict_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(
        json={"value": [None, "junk", {"id": "b1", "name": "Todo"}]}
    )
    out = list_planner_buckets("p1")
    assert len(out) == 1
    assert out[0]["id"] == "b1"


@respx.mock
def test_propagates_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(403, json={"error": "forbidden"})
    with pytest.raises(httpx.HTTPStatusError):
        list_planner_buckets("p1")


@respx.mock
def test_empty_value_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(URL_TMPL.format("p1")).respond(json={"value": []})
    assert list_planner_buckets("p1") == []
