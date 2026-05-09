# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: Planner read tools against the real Microsoft Graph.

These tests are tolerant to data shape — the harness account may or
may not be a member of any M365 group, and any group it's in may or
may not have Planner plans. Tests assert on **shape** when data is
present and **graceful skip** when it isn't.

This is fine for v0.1 because the read tools' contract is "return the
unified envelope when there's data; return [] when there isn't" — the
shape assertions are the actual contract test.
"""

from __future__ import annotations

import pytest

from microsoft_tasks_mcp.auth.store import DEFAULT_CACHE_DIR
from microsoft_tasks_mcp.tools.planner_buckets import list_planner_buckets
from microsoft_tasks_mcp.tools.planner_plan_get import get_planner_plan
from microsoft_tasks_mcp.tools.planner_plans import list_planner_plans
from microsoft_tasks_mcp.tools.planner_task_get import get_planner_task
from microsoft_tasks_mcp.tools.planner_tasks import list_planner_tasks

HARNESS_PROFILE = "harness"


def _harness_token_present() -> bool:
    return (DEFAULT_CACHE_DIR / HARNESS_PROFILE / "token.json").exists()


_SKIP_REASON = (
    "Harness profile token not cached. Run "
    "`mcp-server-microsoft-tasks login --profile harness` once."
)


@pytest.fixture(autouse=True)
def _file_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_planner_plans_returns_a_list_envelope() -> None:
    """Shape contract: result is a list, each entry has the documented
    keys. Empty list (no Planner plans visible to the user) is valid."""
    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=20)
    assert isinstance(plans, list)
    for plan in plans:
        assert set(plan.keys()) >= {"id", "title", "owner_group_id", "etag"}
        assert isinstance(plan["id"], str) and plan["id"]


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_planner_plan_get_round_trips_first_visible_plan() -> None:
    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=1)
    if not plans:
        pytest.skip("harness account sees no Planner plans")
    fetched = get_planner_plan(plans[0]["id"], profile=HARNESS_PROFILE)
    assert fetched["id"] == plans[0]["id"]
    assert fetched["title"] == plans[0]["title"]


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_planner_buckets_for_first_visible_plan() -> None:
    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=1)
    if not plans:
        pytest.skip("harness account sees no Planner plans")
    buckets = list_planner_buckets(plans[0]["id"], profile=HARNESS_PROFILE)
    assert isinstance(buckets, list)
    for bucket in buckets:
        assert bucket["plan_id"] == plans[0]["id"]
        assert isinstance(bucket["name"], str)


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_planner_tasks_for_first_visible_plan() -> None:
    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=1)
    if not plans:
        pytest.skip("harness account sees no Planner plans")
    tasks = list_planner_tasks(
        plans[0]["id"],
        profile=HARNESS_PROFILE,
        limit=10,
    )
    assert isinstance(tasks, list)
    for task in tasks:
        assert task["source"] == "planner"
        assert task["plan_id"] == plans[0]["id"]
        assert task["status"] in {"completed", "not_completed", None}


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_planner_task_get_round_trips_first_visible_task() -> None:
    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=1)
    if not plans:
        pytest.skip("harness account sees no Planner plans")
    tasks = list_planner_tasks(plans[0]["id"], profile=HARNESS_PROFILE, limit=1)
    if not tasks:
        pytest.skip("first visible plan has no tasks")
    fetched = get_planner_task(tasks[0]["id"], profile=HARNESS_PROFILE)
    assert fetched["id"] == tasks[0]["id"]


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_planner_task_web_url_constructed_and_reachable() -> None:
    """Issue #27 acceptance criterion: the deep-link the envelope
    builds from the JWT `tid` claim must actually resolve when followed."""
    import httpx

    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=1)
    if not plans:
        pytest.skip("harness account sees no Planner plans")
    tasks = list_planner_tasks(plans[0]["id"], profile=HARNESS_PROFILE, limit=1)
    if not tasks:
        pytest.skip("first visible plan has no tasks")
    web_url = tasks[0]["web_url"]
    assert isinstance(web_url, str), (
        f"expected web_url to be populated for Planner tasks; got {web_url!r}"
    )
    assert web_url.startswith("https://tasks.office.com/")
    # Microsoft serves a SPA from tasks.office.com that auth-redirects
    # unauthenticated visitors; we don't follow auth, just confirm the
    # host doesn't return a hard error.
    response = httpx.head(web_url, follow_redirects=False, timeout=15.0)
    assert response.status_code < 500, (
        f"unexpected server error when following web_url: {response.status_code}"
    )


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_planner_task_get_with_details() -> None:
    """include_details=True must additionally fetch /details and fold
    in description / checklist / references / preview_type."""
    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=1)
    if not plans:
        pytest.skip("harness account sees no Planner plans")
    tasks = list_planner_tasks(plans[0]["id"], profile=HARNESS_PROFILE, limit=1)
    if not tasks:
        pytest.skip("first visible plan has no tasks")
    detailed = get_planner_task(
        tasks[0]["id"],
        include_details=True,
        profile=HARNESS_PROFILE,
    )
    # Either string (with content) or empty string (no description set)
    # — both pass the type check; the load-bearing thing is presence.
    assert "description" in detailed
    assert "checklist" in detailed
    assert "references" in detailed
