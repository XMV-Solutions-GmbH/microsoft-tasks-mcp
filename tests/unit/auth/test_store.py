# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the auth/store shim."""

from __future__ import annotations

from pathlib import Path

import pytest

from microsoft_tasks_mcp.auth import store


def test_constants() -> None:
    assert store.KEYRING_SERVICE == "mcp-server-microsoft-tasks"
    assert store.DEFAULT_CACHE_DIR == Path.home() / ".cache" / "mcp-server-microsoft-tasks"
    assert store.PASSPHRASE_ENV == "MS_TASKS_TOKEN_PASSPHRASE"
    assert store.STORE_OVERRIDE_ENV == "MS_TASKS_TOKEN_STORE"


def test_get_token_store_forced_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(store.STORE_OVERRIDE_ENV, "file")
    assert isinstance(store.get_token_store(), store.PlainFileTokenStore)


def test_get_token_store_forced_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(store.STORE_OVERRIDE_ENV, "keyring")
    assert isinstance(store.get_token_store(), store.KeyringTokenStore)


def test_get_token_store_forced_encrypted_requires_passphrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(store.STORE_OVERRIDE_ENV, "encrypted-file")
    monkeypatch.delenv(store.PASSPHRASE_ENV, raising=False)
    with pytest.raises(store.NoUsableTokenStoreError, match="MS_TASKS_TOKEN_PASSPHRASE"):
        store.get_token_store()


def test_get_token_store_forced_encrypted_with_passphrase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(store.STORE_OVERRIDE_ENV, "encrypted-file")
    monkeypatch.setenv(store.PASSPHRASE_ENV, "test-passphrase-not-a-secret")
    backend = store.get_token_store()
    assert isinstance(backend, store.EncryptedFileTokenStore)


def test_get_token_store_forced_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(store.STORE_OVERRIDE_ENV, "sqlite")
    with pytest.raises(
        store.NoUsableTokenStoreError, match="must be 'keyring', 'file', or 'encrypted-file'"
    ):
        store.get_token_store()


def test_get_token_store_auto_no_keyring_no_passphrase_picks_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the OS has no real keyring and no passphrase is set, fall
    back to the plain-file backend (which is what CI runners hit)."""
    monkeypatch.delenv(store.STORE_OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(store.PASSPHRASE_ENV, raising=False)
    monkeypatch.setattr(store, "is_real_keyring_backend", lambda _: False)
    assert isinstance(store.get_token_store(), store.PlainFileTokenStore)


def test_get_token_store_auto_with_passphrase_picks_encrypted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No real keyring, passphrase set → encrypted-file backend."""
    monkeypatch.delenv(store.STORE_OVERRIDE_ENV, raising=False)
    monkeypatch.setenv(store.PASSPHRASE_ENV, "test-passphrase-not-a-secret")
    monkeypatch.setattr(store, "is_real_keyring_backend", lambda _: False)
    assert isinstance(store.get_token_store(), store.EncryptedFileTokenStore)


def test_get_token_store_auto_with_real_keyring_picks_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(store.STORE_OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(store.PASSPHRASE_ENV, raising=False)
    monkeypatch.setattr(store, "is_real_keyring_backend", lambda _: True)
    assert isinstance(store.get_token_store(), store.KeyringTokenStore)


def test_plain_file_backend_writes_under_override_dir(tmp_path: Path) -> None:
    """Behavioural check: `set` + `get` round-trip via the override dir.

    Beats poking at private attributes — exercises what the contract
    actually promises (read-your-write) through the override path."""
    backend = store.PlainFileTokenStore(base_dir=tmp_path)
    backend.set("harness", b'{"access_token":"AT-test"}')
    assert backend.get("harness") == b'{"access_token":"AT-test"}'
    # Default-named profile must not collide.
    assert backend.get("default") is None
