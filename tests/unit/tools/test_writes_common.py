# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the shared write-tool guards."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import (
    ExternallyModifiedError,
    NotOwnedByProfileError,
    require_owned_by_profile,
)


def _entry(graph_id: str = "g1", source: Literal["todo", "planner"] = "todo") -> TaskEntry:
    return TaskEntry(
        source=source,
        graph_id=graph_id,
        list_or_plan_id="L1",
        title="T",
        etag='W/"e"',
        created_at=0.0,
    )


def test_require_owned_returns_entry_when_present(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    out = require_owned_by_profile(registry=reg, graph_id="g1", expected_source="todo")
    assert out.graph_id == "g1"


def test_require_owned_raises_when_missing(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError) as exc_info:
        require_owned_by_profile(registry=reg, graph_id="g999", expected_source="todo")
    assert "NOT_OWNED_BY_PROFILE" in str(exc_info.value)
    assert exc_info.value.graph_id == "g999"
    assert exc_info.value.source == "todo"


def test_require_owned_rejects_source_mismatch(tmp_path: Path) -> None:
    """A planner task in the registry must not pass a 'todo' guard."""
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1", source="planner"))
    with pytest.raises(NotOwnedByProfileError):
        require_owned_by_profile(registry=reg, graph_id="g1", expected_source="todo")


def test_externally_modified_error_message_carries_graph_id() -> None:
    err = ExternallyModifiedError("g1")
    assert "EXTERNALLY_MODIFIED" in str(err)
    assert err.graph_id == "g1"
