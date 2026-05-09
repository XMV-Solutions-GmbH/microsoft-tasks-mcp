# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_task_complete."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import NotOwnedByProfileError
from microsoft_tasks_mcp.tools.todo_task_complete import complete_todo_task

URL_TMPL = "https://graph.microsoft.com/v1.0/me/todo/lists/{}/tasks/{}"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_task_update.get_token",
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
            etag='W/"e"',
            created_at=0.0,
        )
    )
    return reg


@respx.mock
def test_completes_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    route = respx.patch(URL_TMPL.format("L1", "T1")).respond(
        json={"id": "T1", "title": "X", "status": "completed"}
    )
    out = complete_todo_task("T1", registry=reg)
    assert out["status"] == "completed"
    sent = route.calls.last.request.read().decode()
    assert '"completed"' in sent


def test_unowned_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        complete_todo_task("T1", registry=reg)
