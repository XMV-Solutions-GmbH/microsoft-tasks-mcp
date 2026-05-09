# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: tasks_assigned_to_me + tasks_search against the real Microsoft Graph."""

from __future__ import annotations

import pytest

from microsoft_tasks_mcp.auth.store import DEFAULT_CACHE_DIR
from microsoft_tasks_mcp.tools.tasks_assigned_to_me import assigned_to_me
from microsoft_tasks_mcp.tools.tasks_search import search

HARNESS_PROFILE = "harness"


def _harness_token_present() -> bool:
    return (DEFAULT_CACHE_DIR / HARNESS_PROFILE / "token.json").exists()


_SKIP_REASON = (
    "Harness profile token not cached. Run "
    "`mcp-server-microsoft-tasks login --profile harness` once."
)


@pytest.fixture(autouse=True)
def _file_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_tasks_assigned_to_me_returns_envelope_shape() -> None:
    """Shape contract: list of unified envelopes, each tagged with
    `source` ("todo" or "planner"). Empty is valid."""
    out = assigned_to_me(profile=HARNESS_PROFILE, limit=20)
    assert isinstance(out, list)
    for task in out:
        assert task["source"] in {"todo", "planner"}
        assert "id" in task and "title" in task
        assert task["status"] in {"completed", "not_completed", None}


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_tasks_search_returns_list_for_arbitrary_query() -> None:
    """Search a query that's unlikely to match anything; must return
    a list (possibly empty), never raise."""
    out = search(
        "this-query-string-must-not-match-anything-x7y9z3",
        profile=HARNESS_PROFILE,
        limit=10,
    )
    assert isinstance(out, list)
    assert out == [] or all(t["source"] in {"todo", "planner"} for t in out)


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_tasks_search_respects_source_narrow_to_todo() -> None:
    """source='todo' must not return any planner items."""
    out = search("a", source="todo", profile=HARNESS_PROFILE, limit=10)
    assert isinstance(out, list)
    for task in out:
        assert task["source"] == "todo"
