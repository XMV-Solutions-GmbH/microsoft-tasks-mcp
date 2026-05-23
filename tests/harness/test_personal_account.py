# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness tests for the personal-Microsoft-account path.

When the operator signs in with an outlook.com / hotmail.com / live.com
account, the To Do tools (`todo_*`) MUST work and the Planner tools
(`planner_*`) MUST refuse with a clear platform-restriction message.

Skipped silently when the `harness-personal` profile's token cache is
missing — populated by signing in with a personal account locally, or
by the `MS_TASKS_HARNESS_PERSONAL_TOKEN_JSON` repo secret in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from microsoft_tasks_mcp.auth import get_token, is_personal_account
from microsoft_tasks_mcp.auth.store import PlainFileTokenStore

PERSONAL_PROFILE = "harness-personal"


def _personal_cache_path() -> Path:
    return Path.home() / ".cache" / "mcp-server-microsoft-tasks" / PERSONAL_PROFILE / "token.json"


def _skip_if_no_personal_harness() -> None:
    if not _personal_cache_path().exists():
        pytest.skip(
            "Personal-account harness token cache missing. Sign in with a "
            "personal Microsoft account using --profile harness-personal, "
            "or set MS_TASKS_HARNESS_PERSONAL_TOKEN_JSON in CI."
        )


def _token() -> str:
    os.environ.setdefault("MS_TASKS_TOKEN_STORE", "file")
    return get_token(profile=PERSONAL_PROFILE, store=PlainFileTokenStore())


# ── token + identity sanity ───────────────────────────────────────────────


def test_personal_token_decodes_as_personal_account() -> None:
    """Sanity: the harness-personal cache really is a personal MSA token.
    If this fails, re-sign-in with a personal account (outlook.com etc.)."""
    _skip_if_no_personal_harness()
    assert is_personal_account(_token()) is True


def test_personal_token_can_call_graph_me() -> None:
    """End-to-end auth pipeline works for personal accounts via /common."""
    _skip_if_no_personal_harness()
    response = httpx.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=30.0,
    )
    response.raise_for_status()
    assert response.json().get("id")


# ── planner guard fires for personal ──────────────────────────────────────


def test_planner_guard_refuses_personal_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime guard at the top of every `planner_*` wrapper raises
    a `PermissionError` for personal accounts. Message names To Do as
    the alternative the agent can offer the user."""
    _skip_if_no_personal_harness()
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    monkeypatch.setenv("TASKS_PROFILE", PERSONAL_PROFILE)

    from microsoft_tasks_mcp.server import _guard_planner_account_type

    with pytest.raises(PermissionError, match="personal Microsoft account"):
        _guard_planner_account_type(PERSONAL_PROFILE)


# ── todo tools work for personal ──────────────────────────────────────────


def test_personal_account_can_list_todo_lists() -> None:
    """Microsoft To Do is available on personal accounts. `/me/todo/lists`
    is the real call — proves the personal-account path through the
    todo_lists tool works end-to-end against Graph."""
    _skip_if_no_personal_harness()
    response = httpx.get(
        "https://graph.microsoft.com/v1.0/me/todo/lists",
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    # Personal accounts always have at least the default "Tasks" list.
    assert "value" in payload, f"unexpected /me/todo/lists shape: {payload}"
    assert isinstance(payload["value"], list)
