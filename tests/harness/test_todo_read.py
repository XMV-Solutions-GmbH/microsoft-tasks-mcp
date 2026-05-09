# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: To Do read tools against the real Microsoft Graph.

Every M365 user has at least the default Tasks list (`wellknownListName
== "defaultList"`), so these tests don't need a separately provisioned
sandbox — they exercise whatever's already on `d.koller@xmv.de`'s
account. No mutations.
"""

from __future__ import annotations

import pytest

from microsoft_tasks_mcp.auth.store import DEFAULT_CACHE_DIR
from microsoft_tasks_mcp.tools.todo_list_get import get_todo_list
from microsoft_tasks_mcp.tools.todo_lists import list_todo_lists
from microsoft_tasks_mcp.tools.todo_task_get import get_todo_task
from microsoft_tasks_mcp.tools.todo_tasks import list_todo_tasks

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
def test_todo_lists_returns_at_least_default_list() -> None:
    lists = list_todo_lists(profile=HARNESS_PROFILE)
    assert isinstance(lists, list) and lists, "expected at least one To Do list"
    well_known = {entry["well_known_list_name"] for entry in lists}
    assert "defaultList" in well_known, (
        f"expected the built-in defaultList among harness lists; got {well_known}"
    )


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_todo_list_get_round_trips_default_list() -> None:
    lists = list_todo_lists(profile=HARNESS_PROFILE)
    default = next(
        (entry for entry in lists if entry["well_known_list_name"] == "defaultList"),
        None,
    )
    assert default is not None
    fetched = get_todo_list(default["id"], profile=HARNESS_PROFILE)
    assert fetched["id"] == default["id"]
    assert fetched["display_name"] == default["display_name"]


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_todo_tasks_against_default_list_returns_envelope_shape() -> None:
    """List tasks in the user's default list. Tolerant: empty is OK."""
    lists = list_todo_lists(profile=HARNESS_PROFILE)
    default = next(
        (entry for entry in lists if entry["well_known_list_name"] == "defaultList"),
        None,
    )
    assert default is not None
    tasks = list_todo_tasks(default["id"], profile=HARNESS_PROFILE, limit=10)
    assert isinstance(tasks, list)
    for task in tasks:
        assert task["source"] == "todo"
        assert task["list_id"] == default["id"]
        assert task["status"] in {"completed", "not_completed", None}
        assert task["assignees"] == []


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_todo_task_get_round_trips_first_task_if_any() -> None:
    """Defensive: skip when the harness account has no tasks at all."""
    lists = list_todo_lists(profile=HARNESS_PROFILE)
    default = next(
        (entry for entry in lists if entry["well_known_list_name"] == "defaultList"),
        None,
    )
    assert default is not None
    tasks = list_todo_tasks(default["id"], profile=HARNESS_PROFILE, limit=1)
    if not tasks:
        pytest.skip("no tasks in default list — nothing to round-trip")
    first = tasks[0]
    fetched = get_todo_task(default["id"], first["id"], profile=HARNESS_PROFILE)
    assert fetched["id"] == first["id"]
    assert fetched["title"] == first["title"]
