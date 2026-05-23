# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_task_update."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry
from microsoft_tasks_mcp.tools._writes_common import (
    ExternallyModifiedError,
    NotOwnedByProfileError,
)
from microsoft_tasks_mcp.tools.todo_task_update import update_todo_task

URL_TMPL = "https://graph.microsoft.com/v1.0/me/todo/lists/{}/tasks/{}"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_task_update.get_token",
        lambda profile: token,
    )


def _seed_registry(tmp_path: Path, etag: str | None = 'W/"old"') -> TaskRegistry:
    reg = TaskRegistry("default", base_dir=tmp_path)
    reg.add(
        TaskEntry(
            source="todo",
            graph_id="T1",
            list_or_plan_id="L1",
            title="Old",
            etag=etag,
            created_at=0.0,
        )
    )
    return reg


@respx.mock
def test_updates_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.patch(URL_TMPL.format("L1", "T1")).respond(
        json={"id": "T1", "title": "New", "@odata.etag": 'W/"new"'}
    )
    out = update_todo_task("T1", title="New", registry=reg)
    assert out["title"] == "New"
    # ETag in registry refreshed
    refreshed = reg.get("T1")
    assert refreshed is not None
    assert refreshed.etag == 'W/"new"'


@respx.mock
def test_passes_if_match_header(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path, etag='W/"v1"')
    route = respx.patch(URL_TMPL.format("L1", "T1")).respond(
        json={"id": "T1", "title": "X", "@odata.etag": 'W/"v2"'}
    )
    update_todo_task("T1", title="X", registry=reg)
    assert route.calls.last.request.headers["If-Match"] == 'W/"v1"'


@respx.mock
def test_412_raises_externally_modified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.patch(URL_TMPL.format("L1", "T1")).respond(412, json={"error": "precondition failed"})
    with pytest.raises(ExternallyModifiedError):
        update_todo_task("T1", title="X", registry=reg)


def test_unowned_task_raises_before_http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The guard MUST run before any Graph call. Verify by NOT mocking
    a respx route — if the tool reached HTTP, we'd see a respx error."""
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)  # empty
    with pytest.raises(NotOwnedByProfileError):
        update_todo_task("T1", title="X", registry=reg)


def test_status_completed_maps_to_graph_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with respx.mock:
        route = respx.patch(URL_TMPL.format("L1", "T1")).respond(
            json={"id": "T1", "title": "X", "status": "completed"}
        )
        update_todo_task("T1", status="completed", registry=reg)
        sent = route.calls.last.request.read().decode()
        assert '"status": "completed"' in sent or '"status":"completed"' in sent


def test_status_not_completed_maps_to_graph_notstarted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with respx.mock:
        route = respx.patch(URL_TMPL.format("L1", "T1")).respond(
            json={"id": "T1", "title": "X", "status": "notStarted"}
        )
        update_todo_task("T1", status="not_completed", registry=reg)
        sent = route.calls.last.request.read().decode()
        assert '"notStarted"' in sent


def test_rejects_empty_task_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty task_id"):
        update_todo_task("", title="X", registry=TaskRegistry("default", base_dir=tmp_path))


def test_rejects_invalid_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="status must be"):
        update_todo_task(
            "T1",
            status="urgent",
            registry=TaskRegistry("default", base_dir=tmp_path),
        )


def test_rejects_invalid_importance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="importance must be"):
        update_todo_task(
            "T1",
            importance="urgent",
            registry=TaskRegistry("default", base_dir=tmp_path),
        )


def test_rejects_no_fields_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with pytest.raises(ValueError, match="at least one field"):
        update_todo_task("T1", registry=reg)


def test_rejects_empty_title_when_explicitly_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    with pytest.raises(ValueError, match="title, when given"):
        update_todo_task("T1", title="   ", registry=reg)


@respx.mock
def test_propagates_403(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)
    respx.patch(URL_TMPL.format("L1", "T1")).respond(403, json={"error": "no"})
    with pytest.raises(httpx.HTTPStatusError):
        update_todo_task("T1", title="X", registry=reg)


@respx.mock
def test_no_etag_in_registry_means_no_if_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path, etag=None)
    route = respx.patch(URL_TMPL.format("L1", "T1")).respond(
        json={"id": "T1", "title": "X", "@odata.etag": 'W/"new"'}
    )
    update_todo_task("T1", title="X", registry=reg)
    assert "If-Match" not in route.calls.last.request.headers


# ---------------------------------------------------------------------
# v0.7 (#57) — TASKS_ALLOW_EXTERNAL_WRITES path
# ---------------------------------------------------------------------


@respx.mock
def test_external_write_fetches_fresh_etag_and_patches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With external-writes on AND the task not in the registry,
    update_todo_task must:
    1. fetch the current task to learn the @odata.etag
    2. PATCH with If-Match: <that etag>
    3. NOT add a synthetic registry entry afterwards."""
    monkeypatch.setenv("TASKS_ALLOW_EXTERNAL_WRITES", "true")
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)  # empty

    respx.get(URL_TMPL.format("L-ext", "T-ext")).respond(
        json={
            "id": "T-ext",
            "title": "Manually typed",
            "@odata.etag": 'W/"external"',
        }
    )
    patch_route = respx.patch(URL_TMPL.format("L-ext", "T-ext")).respond(
        json={"id": "T-ext", "title": "Now updated", "@odata.etag": 'W/"after"'}
    )

    out = update_todo_task("T-ext", title="Now updated", list_id="L-ext", registry=reg)
    assert out["title"] == "Now updated"
    # If-Match was carried from the fresh GET
    assert patch_route.calls.last.request.headers["If-Match"] == 'W/"external"'
    # Registry not polluted with a synthetic entry
    assert reg.get("T-ext") is None


def test_external_write_missing_list_id_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The To Do API needs list_id in the URL — without registry entry
    AND without explicit list_id, the tool can't construct the URL."""
    from microsoft_tasks_mcp.tools._writes_common import ExternalListIdRequiredError

    monkeypatch.setenv("TASKS_ALLOW_EXTERNAL_WRITES", "true")
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(ExternalListIdRequiredError):
        update_todo_task("T-ext", title="X", registry=reg)


def test_external_write_flag_off_still_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without TASKS_ALLOW_EXTERNAL_WRITES, the registry guard fires
    even when list_id IS supplied — the flag is the only unlock."""
    monkeypatch.delenv("TASKS_ALLOW_EXTERNAL_WRITES", raising=False)
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    with pytest.raises(NotOwnedByProfileError):
        update_todo_task("T-ext", title="X", list_id="L-ext", registry=reg)


@respx.mock
def test_external_write_in_registry_ignores_explicit_list_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the task IS in the registry, the registry's list_id is
    authoritative — a caller-supplied list_id mismatch must NOT
    redirect the write to the wrong list."""
    monkeypatch.setenv("TASKS_ALLOW_EXTERNAL_WRITES", "true")
    _patch_get_token(monkeypatch)
    reg = _seed_registry(tmp_path)  # entry with list_or_plan_id="L1"
    route = respx.patch(URL_TMPL.format("L1", "T1")).respond(
        json={"id": "T1", "title": "X", "@odata.etag": 'W/"new"'}
    )
    update_todo_task("T1", title="X", list_id="L-wrong", registry=reg)
    # The PATCH went to /L1/..., NOT /L-wrong/...
    assert route.calls.call_count == 1
