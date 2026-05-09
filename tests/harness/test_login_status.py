# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: tasks_login_status against the real harness token cache."""

from __future__ import annotations

import pytest

from microsoft_tasks_mcp.auth.store import DEFAULT_CACHE_DIR
from microsoft_tasks_mcp.login_state import reset_for_tests
from microsoft_tasks_mcp.tools.login_status import login_status

HARNESS_PROFILE = "harness"
EXPECTED_UPN = "d.koller@xmv.de"


def _harness_token_present() -> bool:
    return (DEFAULT_CACHE_DIR / HARNESS_PROFILE / "token.json").exists()


_SKIP_REASON = (
    "Harness profile token not cached. Run "
    "`mcp-server-microsoft-tasks login --profile harness` once."
)


@pytest.mark.skipif(not _harness_token_present(), reason=_SKIP_REASON)
def test_login_status_signed_in_returns_real_upn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tasks_login_status against the harness token cache must return
    `signed_in` and resolve the UPN from a real /me round-trip."""
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")
    reset_for_tests()  # clear UPN cache so /me really fires

    result = login_status(profile=HARNESS_PROFILE)

    assert result["status"] == "signed_in"
    assert result["signed_in_user_upn"] == EXPECTED_UPN
