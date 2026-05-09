# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the tasks_status MCP tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools.tasks_status import status


@pytest.fixture
def _redirect_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the default registry dir at tmp_path so tests don't touch
    the real ~/.cache/mcp-server-microsoft-tasks/."""
    monkeypatch.setattr("microsoft_tasks_mcp.task_registry.DEFAULT_REGISTRY_DIR", tmp_path)
    return tmp_path


def test_empty_returns_empty_list(_redirect_registry: Path) -> None:
    assert status() == []


def test_returns_dicts_for_registered_tasks(_redirect_registry: Path) -> None:
    reg = TaskRegistry("default", base_dir=_redirect_registry)
    reg.add(
        TaskEntry(
            source="todo",
            graph_id="g1",
            list_or_plan_id="L1",
            title="One",
            etag='W/"e1"',
            created_at=1_700_000_000.0,
        )
    )
    reg.add(
        TaskEntry(
            source="planner",
            graph_id="g2",
            list_or_plan_id="P1",
            title="Two",
            etag='W/"e2"',
            created_at=1_700_000_010.0,
        )
    )

    out = status()
    assert len(out) == 2
    keys_set = {tuple(sorted(d.keys())) for d in out}
    assert keys_set == {
        ("created_at", "etag", "graph_id", "list_or_plan_id", "source", "title"),
    }


def test_profile_threads_through(_redirect_registry: Path) -> None:
    """status() must read the registry for the requested profile only."""
    default_reg = TaskRegistry("default", base_dir=_redirect_registry)
    harness_reg = TaskRegistry("harness", base_dir=_redirect_registry)
    default_reg.add(
        TaskEntry(
            source="todo",
            graph_id="d-1",
            list_or_plan_id="L",
            title="default-task",
            etag=None,
            created_at=0.0,
        )
    )
    harness_reg.add(
        TaskEntry(
            source="todo",
            graph_id="h-1",
            list_or_plan_id="L",
            title="harness-task",
            etag=None,
            created_at=0.0,
        )
    )

    assert [d["graph_id"] for d in status(profile="default")] == ["d-1"]
    assert [d["graph_id"] for d in status(profile="harness")] == ["h-1"]
