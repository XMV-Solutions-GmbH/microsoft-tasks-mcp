# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness: end-to-end auth smoke against the real Microsoft Graph.

This is the harness-gate test from `ENGINEERING_PRINCIPLES.md` § 5: no
v0.1 feature ticket lands before this is green. It proves that:

1. The `harness` profile's cached refresh token (from
   `~/.cache/mcp-server-microsoft-tasks/harness/token.json` locally, or
   the `MS_TASKS_HARNESS_TOKEN_JSON` repo secret in CI) is usable.
2. `auth.get_token()` exchanges it for a fresh access token without
   blocking on user interaction.
3. The access token authenticates against `graph.microsoft.com/v1.0/me`
   and returns the expected UPN.

Skipped automatically when the local token cache is missing — keeps
the harness layer green on dev machines that haven't run
`uvx mcp-server-microsoft-tasks login --profile harness` yet.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.auth.store import DEFAULT_CACHE_DIR

HARNESS_PROFILE = "harness"
EXPECTED_UPN = "d.koller@xmv.de"


def _harness_token_present() -> bool:
    """True iff the harness profile has a cached token on disk."""
    return (DEFAULT_CACHE_DIR / HARNESS_PROFILE / "token.json").exists()


@pytest.mark.skipif(
    not _harness_token_present(),
    reason=(
        f"Harness profile token not cached at "
        f"{DEFAULT_CACHE_DIR / HARNESS_PROFILE / 'token.json'}. "
        "Run `uvx mcp-server-microsoft-tasks login --profile harness` once."
    ),
)
def test_auth_round_trip_to_me(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round-trip: refresh token → access token → /me → UPN match.

    Pin the token store to file backend so this works the same way on
    a developer machine (where keyring would otherwise be picked) and
    on CI (which has no keyring at all). The CI workflow already sets
    MS_TASKS_TOKEN_STORE=file; the monkeypatch makes the test
    self-contained for local runs.
    """
    monkeypatch.setenv("MS_TASKS_TOKEN_STORE", "file")

    access_token = get_token(profile=HARNESS_PROFILE)
    assert access_token, "get_token must return a non-empty access token string"

    response = httpx.get(
        "https://graph.microsoft.com/v1.0/me",
        params={"$select": "userPrincipalName"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15.0,
    )
    response.raise_for_status()
    payload = response.json()
    assert payload.get("userPrincipalName") == EXPECTED_UPN, (
        f"Expected harness profile to be {EXPECTED_UPN!r}, got "
        f"{payload.get('userPrincipalName')!r}. Token may be for the wrong account."
    )


def test_token_cache_path_is_under_default_cache_dir() -> None:
    """Sanity: the path the test skipif() consults is the same path the
    auth shim writes to, so the test can't pass while the cache is at
    a stale location."""
    expected = Path.home() / ".cache" / "mcp-server-microsoft-tasks" / HARNESS_PROFILE
    assert (DEFAULT_CACHE_DIR / HARNESS_PROFILE) == expected
