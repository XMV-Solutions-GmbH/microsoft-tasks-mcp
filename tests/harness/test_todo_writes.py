# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: To Do write tools against the real Microsoft Graph.

End-to-end create → update → complete → delete cycle on the
harness account's default Tasks list. Each test self-cleans even on
failure (the registry is on disk under tmp_path so it doesn't
contaminate other runs; the actual Microsoft Graph state is cleaned
up in a try/finally).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from microsoft_tasks_mcp.auth.store import DEFAULT_CACHE_DIR
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools.todo_lists import list_todo_lists
from microsoft_tasks_mcp.tools.todo_task_complete import complete_todo_task
from microsoft_tasks_mcp.tools.todo_task_create import create_todo_task
from microsoft_tasks_mcp.tools.todo_task_delete import delete_todo_task
from microsoft_tasks_mcp.tools.todo_task_get import get_todo_task
from microsoft_tasks_mcp.tools.todo_task_update import update_todo_task

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
    """Use a tmp-path-backed registry so harness writes don't contaminate
    the real ~/.cache registry of the harness profile."""
    return TaskRegistry(HARNESS_PROFILE, base_dir=tmp_path)


@pytest.fixture
def _default_list_id() -> str:
    """Resolve the harness account's default Tasks list id."""
    if not _harness_token_present():
        pytest.skip(_SKIP_REASON)
    lists = list_todo_lists(profile=HARNESS_PROFILE)
    default = next(
        (entry for entry in lists if entry["well_known_list_name"] == "defaultList"),
        None,
    )
    assert default is not None
    return str(default["id"])


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_create_then_get_then_delete_round_trip(
    _registry: TaskRegistry,
    _default_list_id: str,
) -> None:
    title = f"harness write smoke {uuid.uuid4()}"
    created = create_todo_task(
        _default_list_id,
        title,
        profile=HARNESS_PROFILE,
        registry=_registry,
    )
    task_id = created["id"]
    assert isinstance(task_id, str) and task_id

    try:
        # Round-trip via get to confirm it's actually on Graph.
        fetched = get_todo_task(_default_list_id, task_id, profile=HARNESS_PROFILE)
        assert fetched["id"] == task_id
        assert fetched["title"] == title

        # Registry has it.
        assert _registry.get(task_id) is not None
    finally:
        delete_todo_task(task_id, profile=HARNESS_PROFILE, registry=_registry)
        assert _registry.get(task_id) is None


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_update_changes_title_and_refreshes_etag(
    _registry: TaskRegistry,
    _default_list_id: str,
) -> None:
    original = f"harness original {uuid.uuid4()}"
    new_title = f"harness updated {uuid.uuid4()}"
    created = create_todo_task(
        _default_list_id,
        original,
        profile=HARNESS_PROFILE,
        registry=_registry,
    )
    task_id = str(created["id"])
    original_etag = _registry.get(task_id).etag  # type: ignore[union-attr]

    try:
        updated = update_todo_task(
            task_id,
            title=new_title,
            profile=HARNESS_PROFILE,
            registry=_registry,
        )
        assert updated["title"] == new_title
        # ETag refreshed
        new_etag = _registry.get(task_id).etag  # type: ignore[union-attr]
        assert new_etag != original_etag
    finally:
        delete_todo_task(task_id, profile=HARNESS_PROFILE, registry=_registry)


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_complete_marks_task_completed(
    _registry: TaskRegistry,
    _default_list_id: str,
) -> None:
    title = f"harness complete {uuid.uuid4()}"
    created = create_todo_task(
        _default_list_id,
        title,
        profile=HARNESS_PROFILE,
        registry=_registry,
    )
    task_id = str(created["id"])

    try:
        completed = complete_todo_task(task_id, profile=HARNESS_PROFILE, registry=_registry)
        assert completed["status"] == "completed"
    finally:
        delete_todo_task(task_id, profile=HARNESS_PROFILE, registry=_registry)
