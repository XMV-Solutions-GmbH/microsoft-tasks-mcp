# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_plans."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_tasks_mcp.tools.planner_plans import list_planner_plans

GROUPS_URL = "https://graph.microsoft.com/v1.0/me/memberOf"
GROUP_PLANS_URL_TMPL = "https://graph.microsoft.com/v1.0/groups/{}/planner/plans"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_plans.get_token",
        lambda profile: token,
    )


@respx.mock
def test_with_group_id_lists_plans_for_that_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(GROUP_PLANS_URL_TMPL.format("g1")).respond(
        json={
            "value": [
                {"id": "p1", "title": "Sprint 5", "owner": "g1"},
                {"id": "p2", "title": "Sprint 6", "owner": "g1"},
            ]
        }
    )
    out = list_planner_plans(group_id="g1")
    assert [plan["id"] for plan in out] == ["p1", "p2"]
    assert out[0]["title"] == "Sprint 5"
    assert out[0]["owner_group_id"] == "g1"


@respx.mock
def test_without_group_id_enumerates_all_m365_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(GROUPS_URL).respond(
        json={
            "value": [
                {"id": "g1", "groupTypes": ["Unified"], "displayName": "Eng"},
                {"id": "g2", "groupTypes": ["Unified"], "displayName": "Ops"},
                # Distribution list — not Unified, must be skipped.
                {"id": "g3", "groupTypes": [], "displayName": "DL"},
                # Non-dict garbage — must be skipped.
                "junk",
            ]
        }
    )
    respx.get(GROUP_PLANS_URL_TMPL.format("g1")).respond(
        json={"value": [{"id": "p1", "title": "Eng plan"}]}
    )
    respx.get(GROUP_PLANS_URL_TMPL.format("g2")).respond(
        json={"value": [{"id": "p2", "title": "Ops plan"}]}
    )

    out = list_planner_plans()
    assert {plan["id"] for plan in out} == {"p1", "p2"}


@respx.mock
def test_skips_groups_returning_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 on one group must not abort the whole enumeration —
    the user might be a member of a group whose Planner is disabled."""
    _patch_get_token(monkeypatch)
    respx.get(GROUPS_URL).respond(
        json={
            "value": [
                {"id": "g1", "groupTypes": ["Unified"]},
                {"id": "g2", "groupTypes": ["Unified"]},
            ]
        }
    )
    respx.get(GROUP_PLANS_URL_TMPL.format("g1")).respond(403, json={"error": "no planner"})
    respx.get(GROUP_PLANS_URL_TMPL.format("g2")).respond(
        json={"value": [{"id": "p2", "title": "Ops"}]}
    )

    out = list_planner_plans()
    assert [plan["id"] for plan in out] == ["p2"]


@respx.mock
def test_respects_limit_across_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(GROUPS_URL).respond(
        json={
            "value": [
                {"id": "g1", "groupTypes": ["Unified"]},
                {"id": "g2", "groupTypes": ["Unified"]},
            ]
        }
    )
    respx.get(GROUP_PLANS_URL_TMPL.format("g1")).respond(
        json={"value": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]}
    )
    # Second group's response shouldn't be consumed if limit already met,
    # but respx doesn't enforce that — just make sure overall result is
    # truncated to the limit.
    respx.get(GROUP_PLANS_URL_TMPL.format("g2")).respond(json={"value": [{"id": "p4"}]})
    out = list_planner_plans(limit=2)
    assert len(out) == 2


@respx.mock
def test_with_group_id_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(GROUP_PLANS_URL_TMPL.format("g1")).respond(json={"value": []})
    list_planner_plans(group_id="  g1  ")  # must not 404


def test_rejects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        list_planner_plans(limit=0)


@respx.mock
def test_propagates_groups_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(GROUPS_URL).respond(401, json={"error": "unauthorized"})
    with pytest.raises(httpx.HTTPStatusError):
        list_planner_plans()


@respx.mock
def test_handles_missing_owner_field(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(GROUP_PLANS_URL_TMPL.format("g1")).respond(
        json={
            "value": [
                {
                    "id": "p1",
                    "title": "X",
                    "container": {"containerId": "c1", "type": "group"},
                }
            ]
        }
    )
    out = list_planner_plans(group_id="g1")
    assert out[0]["owner_group_id"] == "c1"
