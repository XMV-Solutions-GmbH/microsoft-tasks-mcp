# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the auth public API (`microsoft_tasks_mcp.auth`)."""

from __future__ import annotations

from typing import Any

import pytest

from microsoft_tasks_mcp import auth
from microsoft_tasks_mcp.auth import flow


def test_resolve_client_id_env_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth.CLIENT_ID_ENV, "11111111-1111-1111-1111-111111111111")
    assert auth._resolve_client_id(None) == "11111111-1111-1111-1111-111111111111"


def test_resolve_client_id_explicit_arg_wins_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(auth.CLIENT_ID_ENV, "from-env")
    assert auth._resolve_client_id("from-arg") == "from-arg"


def test_resolve_client_id_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(auth.CLIENT_ID_ENV, raising=False)
    assert auth._resolve_client_id(None) == flow.DEFAULT_CLIENT_ID


def test_resolve_tenant_env_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth.TENANT_ENV, "contoso.onmicrosoft.com")
    assert auth._resolve_tenant(None) == "contoso.onmicrosoft.com"


def test_resolve_tenant_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(auth.TENANT_ENV, raising=False)
    assert auth._resolve_tenant(None) == flow.DEFAULT_AUTHORITY_TENANT


def test_auth_required_error_message_points_at_correct_login_command() -> None:
    """The error message must guide the user to the right CLI command for
    THIS server, not a sister server's command. Catches copy-paste rot."""
    err = auth.AuthRequiredError("harness", "no cached credentials found")
    msg = str(err)
    assert "mcp-server-microsoft-tasks login --profile harness" in msg
    assert err.profile == "harness"
    assert err.reason == "no cached credentials found"


class _FakeStore:
    """Minimal in-memory stand-in for the lib's TokenStore protocol."""

    def __init__(self, payload: bytes | None = None) -> None:
        self._payload = payload
        self.deleted_profiles: list[str] = []
        self.set_profiles: list[tuple[str, bytes]] = []

    def get(self, profile: str) -> bytes | None:
        return self._payload

    def set(self, profile: str, value: bytes) -> None:
        self.set_profiles.append((profile, value))
        self._payload = value

    def delete(self, profile: str) -> None:
        self.deleted_profiles.append(profile)
        self._payload = None


def test_get_token_raises_when_cache_empty() -> None:
    fake = _FakeStore(payload=None)
    with pytest.raises(auth.AuthRequiredError) as exc_info:
        auth.get_token("default", store=fake)
    assert "no cached credentials found" in str(exc_info.value)


def test_get_token_returns_cached_when_not_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-expired CachedToken should be returned without hitting the
    refresh-token round-trip."""
    fake = _FakeStore()

    class _StubCached:
        access_token = "AT-cached"
        refresh_token = "RT-cached"

        @classmethod
        def from_json(cls, _payload: str) -> _StubCached:
            return cls()

        def is_expired(self) -> bool:
            return False

    fake._payload = b'{"access_token":"AT-cached"}'
    monkeypatch.setattr(auth, "CachedToken", _StubCached)

    # If the refresher were called, this would blow up — verify it isn't.
    def _no_refresh(**_kwargs: Any) -> Any:
        raise AssertionError("refresh_access_token must not be called for live token")

    monkeypatch.setattr(auth, "refresh_access_token", _no_refresh)

    assert auth.get_token("default", store=fake) == "AT-cached"


def test_get_token_refreshes_when_expired_with_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeStore()

    class _StubCachedExpired:
        access_token = "AT-old"
        refresh_token = "RT-old"

        @classmethod
        def from_json(cls, _payload: str) -> _StubCachedExpired:
            return cls()

        def is_expired(self) -> bool:
            return True

    class _StubNewCached:
        access_token = "AT-new"

        def to_json(self) -> str:
            return '{"access_token":"AT-new"}'

    fake._payload = b'{"access_token":"AT-old"}'
    monkeypatch.setattr(auth, "CachedToken", _StubCachedExpired)

    captured: dict[str, Any] = {}

    def fake_refresh(**kwargs: Any) -> _StubNewCached:
        captured.update(kwargs)
        return _StubNewCached()

    monkeypatch.setattr(auth, "refresh_access_token", fake_refresh)

    token = auth.get_token("default", store=fake)
    assert token == "AT-new"
    assert captured["refresh_token"] == "RT-old"
    # The refreshed token must be persisted back to the store.
    assert fake.set_profiles[-1][0] == "default"


def test_get_token_raises_when_expired_and_no_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeStore()

    class _StubCachedNoRefresh:
        access_token = "AT-old"
        refresh_token = None

        @classmethod
        def from_json(cls, _payload: str) -> _StubCachedNoRefresh:
            return cls()

        def is_expired(self) -> bool:
            return True

    fake._payload = b'{"access_token":"AT-old"}'
    monkeypatch.setattr(auth, "CachedToken", _StubCachedNoRefresh)

    with pytest.raises(auth.AuthRequiredError, match="no refresh token is available"):
        auth.get_token("default", store=fake)


def test_get_token_refresh_rejected_deletes_cache_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeStore()

    class _StubCachedExpired:
        access_token = "AT-old"
        refresh_token = "RT-old"

        @classmethod
        def from_json(cls, _payload: str) -> _StubCachedExpired:
            return cls()

        def is_expired(self) -> bool:
            return True

    fake._payload = b'{"access_token":"AT-old"}'
    monkeypatch.setattr(auth, "CachedToken", _StubCachedExpired)

    def fake_refresh(**_kwargs: Any) -> Any:
        raise auth.RefreshTokenInvalidError("invalid_grant")

    monkeypatch.setattr(auth, "refresh_access_token", fake_refresh)

    with pytest.raises(auth.AuthRequiredError, match="rejected by Microsoft Identity"):
        auth.get_token("default", store=fake)

    # Stale cache entry must be cleared so the next attempt starts fresh.
    assert fake.deleted_profiles == ["default"]
