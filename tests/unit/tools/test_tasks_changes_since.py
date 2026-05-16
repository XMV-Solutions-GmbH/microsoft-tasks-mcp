# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for tasks_changes_since."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools.tasks_changes_since import (
    CursorStore,
    _scope_key,
    changes_since,
)

PLAN_URL = "https://graph.microsoft.com/v1.0/planner/plans/p1/tasks"
ASSIGNED_URL = "https://graph.microsoft.com/v1.0/me/planner/tasks"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.tasks_changes_since.get_token",
        lambda profile: token,
    )


def _task(
    task_id: str = "t1",
    title: str = "Task",
    last_modified: str = "2026-01-01T10:00:00Z",
    percent_complete: int = 0,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "title": title,
        "planId": "p1",
        "bucketId": "b1",
        "percentComplete": percent_complete,
        "priority": 5,
        "assignments": {},
        "lastModifiedDateTime": last_modified,
        "createdDateTime": "2026-01-01T09:00:00Z",
        "dueDateTime": None,
        "@odata.etag": f'W/"{task_id}"',
    }


def _plan_scope() -> dict[str, Any]:
    return {"kind": "plan", "plan_id": "p1"}


def _assigned_scope() -> dict[str, Any]:
    return {"kind": "assigned_to_me"}


def _registry_scope() -> dict[str, Any]:
    return {"kind": "registry"}


# ---------------------------------------------------------------------------
# CursorStore unit tests
# ---------------------------------------------------------------------------


def test_cursor_store_load_missing_file(tmp_path: Path) -> None:
    store = CursorStore("default", base_dir=tmp_path)
    assert store.load() == {}


def test_cursor_store_round_trip(tmp_path: Path) -> None:
    store = CursorStore("default", base_dir=tmp_path)
    data = {"abc": {"last_modified_max": "2026-01-01T00:00:00Z", "seen_ids": ["t1"]}}
    store.save(data)
    assert store.load() == data


def test_cursor_store_file_mode_0o600(tmp_path: Path) -> None:
    store = CursorStore("default", base_dir=tmp_path)
    store.save({"x": {}})
    cursor_path = tmp_path / "default" / "cursors.json"
    file_mode = stat.S_IMODE(cursor_path.stat().st_mode)
    assert file_mode == 0o600


# ---------------------------------------------------------------------------
# _scope_key
# ---------------------------------------------------------------------------


def test_scope_key_is_deterministic() -> None:
    scope = {"kind": "plan", "plan_id": "abc"}
    assert _scope_key(scope) == _scope_key(scope)


def test_scope_key_sort_order_independent() -> None:
    a = {"plan_id": "abc", "kind": "plan"}
    b = {"kind": "plan", "plan_id": "abc"}
    assert _scope_key(a) == _scope_key(b)


def test_scope_key_different_scopes_differ() -> None:
    assert _scope_key({"kind": "plan", "plan_id": "p1"}) != _scope_key(
        {"kind": "assigned_to_me"}
    )


# ---------------------------------------------------------------------------
# changes_since — plan scope
# ---------------------------------------------------------------------------


@respx.mock
def test_fresh_cursor_everything_added(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLAN_URL).respond(
        json={"value": [_task("t1"), _task("t2")]}
    )
    result = changes_since(
        _plan_scope(),
        profile="default",
        _cursor_base_dir=tmp_path,
    )
    assert {e["id"] for e in result["added"]} == {"t1", "t2"}
    assert result["modified"] == []
    assert result["removed"] == []
    assert result["cursor_advanced"] is True


@respx.mock
def test_subsequent_poll_no_changes_all_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    respx.get(PLAN_URL).respond(json={"value": [_task("t1", last_modified="2026-01-01T10:00:00Z")]})
    changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    respx.get(PLAN_URL).respond(json={"value": [_task("t1", last_modified="2026-01-01T10:00:00Z")]})
    result = changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    assert result["added"] == []
    assert result["modified"] == []
    assert result["removed"] == []


@respx.mock
def test_new_task_appears_as_added(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    respx.get(PLAN_URL).respond(json={"value": [_task("t1")]})
    changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    respx.get(PLAN_URL).respond(json={"value": [_task("t1"), _task("t2")]})
    result = changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    assert [e["id"] for e in result["added"]] == ["t2"]
    assert result["modified"] == []
    assert result["removed"] == []


@respx.mock
def test_advanced_last_modified_appears_as_modified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    respx.get(PLAN_URL).respond(
        json={"value": [_task("t1", last_modified="2026-01-01T10:00:00Z")]}
    )
    changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    respx.get(PLAN_URL).respond(
        json={"value": [_task("t1", last_modified="2026-01-02T10:00:00Z")]}
    )
    result = changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    assert result["added"] == []
    assert [e["id"] for e in result["modified"]] == ["t1"]
    assert result["removed"] == []


@respx.mock
def test_task_disappears_from_response_is_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    respx.get(PLAN_URL).respond(json={"value": [_task("t1"), _task("t2")]})
    changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    respx.get(PLAN_URL).respond(json={"value": [_task("t1")]})
    result = changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    assert result["added"] == []
    assert result["modified"] == []
    assert len(result["removed"]) == 1
    assert result["removed"][0]["id"] == "t2"


# ---------------------------------------------------------------------------
# Monotonicity guard: stale Graph timestamp must not roll cursor back
# ---------------------------------------------------------------------------


@respx.mock
def test_last_modified_max_monotonic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    respx.get(PLAN_URL).respond(
        json={"value": [_task("t1", last_modified="2026-03-01T00:00:00Z")]}
    )
    changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    respx.get(PLAN_URL).respond(
        json={"value": [_task("t1", last_modified="2026-01-01T00:00:00Z")]}
    )
    changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    store = CursorStore("default", base_dir=tmp_path)
    key = _scope_key(_plan_scope())
    cursor = store.load()[key]
    assert cursor["last_modified_max"] == "2026-03-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Scope-hash keying: two scopes are independent
# ---------------------------------------------------------------------------


@respx.mock
def test_two_scopes_have_independent_cursors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    plan_url_p2 = "https://graph.microsoft.com/v1.0/planner/plans/p2/tasks"
    scope_a = {"kind": "plan", "plan_id": "p1"}
    scope_b = {"kind": "plan", "plan_id": "p2"}

    respx.get(PLAN_URL).respond(json={"value": [_task("t1")]})
    changes_since(scope_a, profile="default", _cursor_base_dir=tmp_path)

    respx.get(plan_url_p2).respond(json={"value": [_task("t99")]})
    result_b = changes_since(scope_b, profile="default", _cursor_base_dir=tmp_path)

    assert [e["id"] for e in result_b["added"]] == ["t99"]

    store = CursorStore("default", base_dir=tmp_path)
    cursors = store.load()
    assert _scope_key(scope_a) in cursors
    assert _scope_key(scope_b) in cursors
    assert _scope_key(scope_a) != _scope_key(scope_b)


# ---------------------------------------------------------------------------
# assigned_to_me scope
# ---------------------------------------------------------------------------


@respx.mock
def test_assigned_to_me_scope_fresh_cursor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(ASSIGNED_URL).respond(json={"value": [_task("ta1")]})
    result = changes_since(
        _assigned_scope(),
        profile="default",
        _cursor_base_dir=tmp_path,
    )
    assert [e["id"] for e in result["added"]] == ["ta1"]
    assert result["modified"] == []
    assert result["removed"] == []


# ---------------------------------------------------------------------------
# registry scope
# ---------------------------------------------------------------------------


def test_registry_scope_only_polls_registry_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    registry = TaskRegistry("default", base_dir=tmp_path)
    registry.add(
        TaskEntry(
            source="planner",
            graph_id="tr1",
            list_or_plan_id="p1",
            title="Registered task",
            etag=None,
            created_at=0.0,
        )
    )

    task_url = "https://graph.microsoft.com/v1.0/planner/tasks/tr1"

    with respx.mock:
        respx.get(task_url).respond(json=_task("tr1", title="Registered task"))
        result = changes_since(
            _registry_scope(),
            profile="default",
            _cursor_base_dir=tmp_path,
            _registry_base_dir=tmp_path,
        )

    assert [e["id"] for e in result["added"]] == ["tr1"]
    assert result["modified"] == []
    assert result["removed"] == []


def test_registry_scope_empty_registry_yields_empty_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    result = changes_since(
        _registry_scope(),
        profile="default",
        _cursor_base_dir=tmp_path,
        _registry_base_dir=tmp_path,
    )
    assert result["added"] == []
    assert result["modified"] == []
    assert result["removed"] == []


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_invalid_scope_kind_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match=r"scope\.kind must be one of"):
        changes_since({"kind": "unknown"}, profile="default")


def test_plan_scope_missing_plan_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match=r"scope\.plan_id"):
        changes_since({"kind": "plan"}, profile="default")


def test_max_results_zero_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="max_results must be positive"):
        changes_since({"kind": "assigned_to_me"}, profile="default", max_results=0)


# ---------------------------------------------------------------------------
# cursor_advanced flag logic
# ---------------------------------------------------------------------------


@respx.mock
def test_cursor_advanced_false_when_truly_nothing_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)

    respx.get(PLAN_URL).respond(
        json={"value": [_task("t1", last_modified="2026-05-01T00:00:00Z")]}
    )
    changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    respx.get(PLAN_URL).respond(
        json={"value": [_task("t1", last_modified="2026-05-01T00:00:00Z")]}
    )
    result = changes_since(_plan_scope(), profile="default", _cursor_base_dir=tmp_path)

    assert result["cursor_advanced"] is False
