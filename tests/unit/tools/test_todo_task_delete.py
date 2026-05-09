# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_task_delete."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import NotOwnedByProfileError
from microsoft_tasks_mcp.tools.todo_task_delete import delete_todo_task

URL_TMPL = "https://graph.microsoft.com/v1.0/me/todo/lists/{}/tasks/{}"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_task_delete.get_token",
        lambda profile: token,
    )


def _seed_registry(tmp_path: Path) -> TaskRegistry:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(
        TaskEntry(
            source="todo",
            graph_id="T1",
            list_or_plan_id="L1",
            title="X",
            etag=None,
            created_at=0.0,
        )
    )
    return reg


@respx.mock
def test_deletes_and_removes_from_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.delete(URL_TMPL.format("L1", "T1")).respond(204)
    delete_todo_task("T1", registry=reg)
    assert reg.get("T1") is None


@respx.mock
def test_404_treated_as_success_and_cleans_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.delete(URL_TMPL.format("L1", "T1")).respond(404, json={"error": "ItemNotFound"})
    delete_todo_task("T1", registry=reg)
    assert reg.get("T1") is None


def test_unowned_raises_before_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        delete_todo_task("T1", registry=reg)


def test_rejects_empty_task_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty task_id"):
        delete_todo_task("", registry=TaskRegistry("default", base_dir=tmp_path))


@respx.mock
def test_propagates_500(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.delete(URL_TMPL.format("L1", "T1")).respond(500, json={"error": "internal"})
    with pytest.raises(httpx.HTTPStatusError):
        delete_todo_task("T1", registry=reg)
    # Registry still has the entry — the delete failed, so we
    # didn't tidy up. (Recovery: agent retries the delete.)
    assert reg.get("T1") is not None
