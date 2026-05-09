# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for todo_task_create."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools.todo_task_create import create_todo_task

URL_TMPL = "https://graph.microsoft.com/v1.0/me/todo/lists/{}/tasks"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.todo_task_create.get_token",
        lambda profile: token,
    )


@respx.mock
def test_creates_task_returns_envelope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    respx.post(URL_TMPL.format("L1")).respond(
        201,
        json={
            "id": "T1",
            "title": "Renew passport",
            "status": "notStarted",
            "@odata.etag": 'W/"e"',
        },
    )
    out = create_todo_task(
        "L1",
        "Renew passport",
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    assert out["id"] == "T1"
    assert out["title"] == "Renew passport"
    assert out["status"] == "not_completed"
    assert out["source"] == "todo"


@respx.mock
def test_adds_to_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    reg = TaskRegistry("default", base_dir=tmp_path)
    respx.post(URL_TMPL.format("L1")).respond(
        201,
        json={"id": "T1", "title": "X", "@odata.etag": 'W/"e"'},
    )
    create_todo_task("L1", "X", registry=reg)
    entry = reg.get("T1")
    assert entry is not None
    assert entry.source == "todo"
    assert entry.list_or_plan_id == "L1"
    assert entry.etag == 'W/"e"'


@respx.mock
def test_passes_optional_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    route = respx.post(URL_TMPL.format("L1")).respond(201, json={"id": "T1", "title": "X"})
    create_todo_task(
        "L1",
        "X",
        body="some details",
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    sent = route.calls.last.request.read().decode()
    assert "some details" in sent
    assert '"contentType"' in sent


@respx.mock
def test_passes_due_date_as_iso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    route = respx.post(URL_TMPL.format("L1")).respond(201, json={"id": "T1", "title": "X"})
    create_todo_task(
        "L1",
        "X",
        due_date="2026-12-31T00:00:00",
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    sent = route.calls.last.request.read().decode()
    assert "2026-12-31T00:00:00" in sent
    assert '"timeZone": "UTC"' in sent or '"timeZone":"UTC"' in sent


@respx.mock
def test_passes_importance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    route = respx.post(URL_TMPL.format("L1")).respond(201, json={"id": "T1", "title": "X"})
    create_todo_task(
        "L1",
        "X",
        importance="high",
        registry=TaskRegistry("default", base_dir=tmp_path),
    )
    sent = route.calls.last.request.read().decode()
    assert '"importance"' in sent
    assert '"high"' in sent


def test_rejects_empty_list_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty list_id"):
        create_todo_task("", "X", registry=TaskRegistry("default", base_dir=tmp_path))


def test_rejects_empty_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="non-empty title"):
        create_todo_task("L1", "", registry=TaskRegistry("default", base_dir=tmp_path))


def test_rejects_invalid_importance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="importance must be"):
        create_todo_task(
            "L1",
            "X",
            importance="urgent",
            registry=TaskRegistry("default", base_dir=tmp_path),
        )


@respx.mock
def test_propagates_403(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_get_token(monkeypatch)
    respx.post(URL_TMPL.format("L1")).respond(403, json={"error": "no"})
    with pytest.raises(httpx.HTTPStatusError):
        create_todo_task("L1", "X", registry=TaskRegistry("default", base_dir=tmp_path))
