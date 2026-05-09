# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for planner_task_complete."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import NotOwnedByProfileError
from microsoft_tasks_mcp.tools.planner_task_complete import complete_planner_task

URL = "https://graph.microsoft.com/v1.0/planner/tasks/T1"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.planner_task_update.get_token",
        lambda profile: token,
    )


@respx.mock
def test_completes_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(
        TaskEntry(
            source="planner",
            graph_id="T1",
            list_or_plan_id="P1",
            title="X",
            etag='W/"e"',
            created_at=0.0,
        )
    )
    route = respx.patch(URL).respond(
        json={
            "id": "T1",
            "planId": "P1",
            "percentComplete": 100,
            "assignments": {},
        }
    )
    out = complete_planner_task("T1", registry=reg)
    assert out["status"] == "completed"
    sent = route.calls.last.request.read().decode()
    assert '"percentComplete": 100' in sent or '"percentComplete":100' in sent


def test_unowned_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        complete_planner_task("T1", registry=reg)
