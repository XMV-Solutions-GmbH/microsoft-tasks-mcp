# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the unified-envelope shape helpers."""

from __future__ import annotations

from microsoft_tasks_mcp.tools._shape import planner_envelope, todo_envelope


def test_planner_envelope_web_url_none_when_tenant_missing() -> None:
    """v0.1/v0.2 default — without tenant_id the deep-link is None."""
    out = planner_envelope({"id": "T1", "title": "X", "percentComplete": 0})
    assert out["web_url"] is None


def test_planner_envelope_web_url_built_when_tenant_present() -> None:
    out = planner_envelope(
        {"id": "T1", "title": "X", "percentComplete": 0},
        tenant_id="11111111-2222-3333-4444-555555555555",
    )
    assert out["web_url"] == (
        "https://tasks.office.com/11111111-2222-3333-4444-555555555555/Home/Task/T1"
    )


def test_planner_envelope_web_url_none_when_id_missing() -> None:
    """Without an id we can't build a deep-link, even if tenant is set."""
    out = planner_envelope({"percentComplete": 0}, tenant_id="tenant-x")
    assert out["web_url"] is None


def test_planner_envelope_web_url_none_when_id_not_string() -> None:
    out = planner_envelope({"id": 12345, "percentComplete": 0}, tenant_id="tenant-x")
    assert out["web_url"] is None


def test_planner_envelope_web_url_none_when_tenant_empty_string() -> None:
    out = planner_envelope({"id": "T1", "percentComplete": 0}, tenant_id="")
    assert out["web_url"] is None


def test_todo_envelope_web_url_remains_none() -> None:
    """To Do has no documented stable public deep-link pattern; the
    envelope must keep returning None until that changes upstream."""
    out = todo_envelope({"id": "T1", "title": "X"}, list_id="L1")
    assert out["web_url"] is None
