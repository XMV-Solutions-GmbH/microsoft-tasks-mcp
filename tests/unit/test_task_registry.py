# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the per-profile task registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry


def _entry(graph_id: str = "g1", **overrides: object) -> TaskEntry:
    base: dict[str, object] = {
        "source": "todo",
        "graph_id": graph_id,
        "list_or_plan_id": "L1",
        "title": "Test task",
        "etag": 'W/"e"',
        "created_at": 1_700_000_000.0,
    }
    base.update(overrides)
    return TaskEntry(**base)  # type: ignore[arg-type]


def test_empty_registry_returns_empty_list(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    assert reg.list_all() == []


def test_add_then_list(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1", title="Task one"))
    assert [e.graph_id for e in reg.list_all()] == ["g1"]


def test_add_persists_across_instances(tmp_path: Path) -> None:
    reg1 = TaskRegistry("default", base_dir=tmp_path)
    reg1.add(_entry("g1"))
    reg2 = TaskRegistry("default", base_dir=tmp_path)
    assert [e.graph_id for e in reg2.list_all()] == ["g1"]


def test_add_replaces_existing_entry(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1", title="Old"))
    reg.add(_entry("g1", title="New"))
    assert [(e.graph_id, e.title) for e in reg.list_all()] == [("g1", "New")]


def test_get_returns_entry(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    fetched = reg.get("g1")
    assert fetched is not None
    assert fetched.graph_id == "g1"


def test_get_returns_none_for_unknown(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    assert reg.get("g999") is None


def test_remove_returns_entry(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    removed = reg.remove("g1")
    assert removed is not None
    assert removed.graph_id == "g1"
    assert reg.list_all() == []


def test_remove_returns_none_for_unknown(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    assert reg.remove("g999") is None
    # Original entry untouched
    assert [e.graph_id for e in reg.list_all()] == ["g1"]


def test_update_etag(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1", etag='W/"old"'))
    reg.update_etag("g1", 'W/"new"')
    fetched = reg.get("g1")
    assert fetched is not None
    assert fetched.etag == 'W/"new"'
    # Other fields untouched
    assert fetched.title == "Test task"


def test_update_etag_missing_entry_is_noop(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.update_etag("g999", 'W/"new"')  # must not raise
    assert reg.list_all() == []


def test_profiles_are_isolated(tmp_path: Path) -> None:
    reg_default = TaskRegistry("default", base_dir=tmp_path)
    reg_harness = TaskRegistry("harness", base_dir=tmp_path)
    reg_default.add(_entry("g1", title="default-task"))
    reg_harness.add(_entry("g1", title="harness-task"))

    default_entry = reg_default.get("g1")
    harness_entry = reg_harness.get("g1")
    assert default_entry is not None and default_entry.title == "default-task"
    assert harness_entry is not None and harness_entry.title == "harness-task"


def test_corrupt_file_treated_as_empty(tmp_path: Path) -> None:
    """A garbage registry file must not crash the server."""
    profile_dir = tmp_path / "default"
    profile_dir.mkdir()
    (profile_dir / "tasks.json").write_text("{not valid json", encoding="utf-8")
    reg = TaskRegistry("default", base_dir=tmp_path)
    assert reg.list_all() == []


def test_skips_non_dict_rows(tmp_path: Path) -> None:
    """Defensive: registry survives a hand-edit that injected a junk row."""
    profile_dir = tmp_path / "default"
    profile_dir.mkdir()
    rows = [
        {
            "source": "todo",
            "graph_id": "good",
            "list_or_plan_id": "L1",
            "title": "ok",
            "etag": None,
            "created_at": 1.0,
        },
        "junk",
        None,
    ]
    (profile_dir / "tasks.json").write_text(json.dumps(rows), encoding="utf-8")
    reg = TaskRegistry("default", base_dir=tmp_path)
    out = reg.list_all()
    assert [e.graph_id for e in out] == ["good"]


def test_file_mode_is_owner_only(tmp_path: Path) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1"))
    file = tmp_path / "default" / "tasks.json"
    assert file.exists()
    mode = file.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


@pytest.mark.parametrize("source", ["todo", "planner"])
def test_supports_both_sources(tmp_path: Path, source: str) -> None:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(_entry("g1", source=source))
    fetched = reg.get("g1")
    assert fetched is not None
    assert fetched.source == source
