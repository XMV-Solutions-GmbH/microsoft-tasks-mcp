# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: Planner write tools against the real Microsoft Graph.

Round-trip create → update → complete → delete cycle against the
harness sandbox plan. Each test creates a transient task, exercises
the operation under test, then deletes the task in a try/finally —
no orphans left behind on the live plan.

Skips gracefully if the harness account doesn't have a Planner plan
visible (e.g. the sandbox group hasn't been provisioned yet).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from microsoft_tasks_mcp.auth.store import DEFAULT_CACHE_DIR
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools.planner_buckets import list_planner_buckets
from microsoft_tasks_mcp.tools.planner_plans import list_planner_plans
from microsoft_tasks_mcp.tools.planner_task_complete import complete_planner_task
from microsoft_tasks_mcp.tools.planner_task_create import create_planner_task
from microsoft_tasks_mcp.tools.planner_task_delete import delete_planner_task
from microsoft_tasks_mcp.tools.planner_task_update import update_planner_task

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


@pytest.fixture
def _registry(tmp_path: Path) -> TaskRegistry:
    return TaskRegistry(HARNESS_PROFILE, base_dir=tmp_path)


@pytest.fixture
def _sandbox() -> tuple[str, str]:
    """Resolve the harness plan id + Todo bucket id.

    Skips if no Planner plan is visible to the harness account.
    """
    if not _harness_token_present():
        pytest.skip(_SKIP_REASON)
    plans = list_planner_plans(profile=HARNESS_PROFILE, limit=10)
    if not plans:
        pytest.skip("harness account sees no Planner plans")
    plan_id = str(plans[0]["id"])
    buckets = list_planner_buckets(plan_id, profile=HARNESS_PROFILE)
    todo_bucket = next(
        (b for b in buckets if b.get("name") == "Todo"), buckets[0] if buckets else None
    )
    if todo_bucket is None:
        pytest.skip("harness plan has no buckets")
    return plan_id, str(todo_bucket["id"])


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_create_then_delete_round_trip(
    _registry: TaskRegistry,
    _sandbox: tuple[str, str],
) -> None:
    plan_id, bucket_id = _sandbox
    title = f"harness write smoke {uuid.uuid4()}"
    created = create_planner_task(
        plan_id,
        bucket_id,
        title,
        profile=HARNESS_PROFILE,
        registry=_registry,
    )
    task_id = str(created["id"])
    try:
        assert created["title"] == title
        assert created["plan_id"] == plan_id
        assert created["bucket_id"] == bucket_id
        assert _registry.get(task_id) is not None
    finally:
        delete_planner_task(task_id, profile=HARNESS_PROFILE, registry=_registry)
        assert _registry.get(task_id) is None


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_update_changes_title_and_refreshes_etag(
    _registry: TaskRegistry,
    _sandbox: tuple[str, str],
) -> None:
    plan_id, bucket_id = _sandbox
    original = f"harness original {uuid.uuid4()}"
    new_title = f"harness updated {uuid.uuid4()}"
    created = create_planner_task(
        plan_id,
        bucket_id,
        original,
        profile=HARNESS_PROFILE,
        registry=_registry,
    )
    task_id = str(created["id"])
    initial_entry = _registry.get(task_id)
    assert initial_entry is not None
    original_etag = initial_entry.etag

    try:
        updated = update_planner_task(
            task_id,
            title=new_title,
            profile=HARNESS_PROFILE,
            registry=_registry,
        )
        assert updated["title"] == new_title
        new_entry = _registry.get(task_id)
        assert new_entry is not None
        assert new_entry.etag != original_etag
    finally:
        delete_planner_task(task_id, profile=HARNESS_PROFILE, registry=_registry)


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_complete_marks_task_completed(
    _registry: TaskRegistry,
    _sandbox: tuple[str, str],
) -> None:
    plan_id, bucket_id = _sandbox
    title = f"harness complete {uuid.uuid4()}"
    created = create_planner_task(
        plan_id,
        bucket_id,
        title,
        profile=HARNESS_PROFILE,
        registry=_registry,
    )
    task_id = str(created["id"])
    try:
        completed = complete_planner_task(task_id, profile=HARNESS_PROFILE, registry=_registry)
        assert completed["status"] == "completed"
    finally:
        delete_planner_task(task_id, profile=HARNESS_PROFILE, registry=_registry)


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_recurrence_create_round_trip(
    _registry: TaskRegistry,
    _sandbox: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create a recurring Planner task via /beta, read it back, assert
    Graph populated `seriesId` + `occurrenceId`, then delete.

    Recurrence requires `MS_TASKS_PLANNER_BETA=true`. We set it here
    and let the harness exercise the real beta endpoint.
    """
    monkeypatch.setenv("MS_TASKS_PLANNER_BETA", "true")
    plan_id, bucket_id = _sandbox
    title = f"harness recurrence {uuid.uuid4()}"
    recurrence = {
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
    created = create_planner_task(
        plan_id,
        bucket_id,
        title,
        recurrence=recurrence,
        profile=HARNESS_PROFILE,
        registry=_registry,
    )
    task_id = str(created["id"])
    try:
        assert created["title"] == title
        rec = created.get("recurrence")
        assert rec is not None, "expected Graph to populate `recurrence` on create"
        # Graph populates seriesId + occurrenceId (=1 for the first occurrence)
        assert isinstance(rec.get("seriesId"), str) and rec["seriesId"]
        assert rec.get("occurrenceId") == 1
        # Pattern we sent should round-trip
        assert rec["schedule"]["pattern"]["type"] == "weekly"
        assert rec["schedule"]["pattern"]["interval"] == 1
    finally:
        delete_planner_task(task_id, profile=HARNESS_PROFILE, registry=_registry)
