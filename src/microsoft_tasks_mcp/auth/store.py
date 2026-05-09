# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Token persistence backends.

Thin shim over `mcp-microsoft-graph-auth`'s `token_store` module: the
backend implementations live in the shared library, this module keeps
Microsoft-Tasks-specific defaults (keyring service name, cache
directory, env-var names) and the env-var-driven auto-pick logic in
`get_token_store()`.
"""

from __future__ import annotations

import os
from pathlib import Path

import keyring
from mcp_microsoft_graph_auth.token_store import (
    EncryptedFileTokenStore as _LibEncryptedFileTokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    KeyringTokenStore as _LibKeyringTokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    NoUsableTokenStoreError as NoUsableTokenStoreError,
)
from mcp_microsoft_graph_auth.token_store import (
    PlainFileTokenStore as _LibPlainFileTokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    TokenStore as TokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    is_real_keyring_backend as is_real_keyring_backend,
)

# Keyring service name — matches the PyPI package name so secrets show
# up sensibly in OS keyring tooling (Keychain Access, secret-tool, etc.).
KEYRING_SERVICE = "mcp-server-microsoft-tasks"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mcp-server-microsoft-tasks"
PASSPHRASE_ENV = "MS_TASKS_TOKEN_PASSPHRASE"
STORE_OVERRIDE_ENV = "MS_TASKS_TOKEN_STORE"

__all__ = [
    "DEFAULT_CACHE_DIR",
    "KEYRING_SERVICE",
    "PASSPHRASE_ENV",
    "STORE_OVERRIDE_ENV",
    "EncryptedFileTokenStore",
    "KeyringTokenStore",
    "NoUsableTokenStoreError",
    "PlainFileTokenStore",
    "TokenStore",
    "get_token_store",
]


class KeyringTokenStore(_LibKeyringTokenStore):
    """Tasks-flavoured keyring backend (default service: 'mcp-server-microsoft-tasks')."""

    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        super().__init__(service_name=service)


class PlainFileTokenStore(_LibPlainFileTokenStore):
    """Plain-file backend.

    Default base_dir: `~/.cache/mcp-server-microsoft-tasks`.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(base_dir=base_dir if base_dir is not None else DEFAULT_CACHE_DIR)


class EncryptedFileTokenStore(_LibEncryptedFileTokenStore):
    """Tasks-flavoured encrypted-file backend.

    Reads the passphrase from `MS_TASKS_TOKEN_PASSPHRASE` (or the override
    `passphrase_env`) at construction time. Construction raises
    `NoUsableTokenStoreError` when the env var is unset or empty.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        passphrase_env: str = PASSPHRASE_ENV,
    ) -> None:
        passphrase = os.environ.get(passphrase_env, "")
        if not passphrase:
            raise NoUsableTokenStoreError(
                f"Encrypted-file token store requires the {passphrase_env} "
                "environment variable to be set and non-empty.",
            )
        super().__init__(
            base_dir=base_dir if base_dir is not None else DEFAULT_CACHE_DIR,
            passphrase=passphrase,
        )


def get_token_store() -> TokenStore:
    """Pick a token-store backend for the current environment.

    Resolution order (no env vars needed for the typical install):

    1. `MS_TASKS_TOKEN_STORE=keyring|file|encrypted-file` — explicit override.
    2. Auto: OS keyring if a real backend is detected (macOS Keychain,
       Windows Credential Locker, Linux Secret Service).
    3. Auto: encrypted-file backend if `MS_TASKS_TOKEN_PASSPHRASE` is set
       (opt-in, useful for CI where the passphrase + ciphertext are
       separate secrets).
    4. Auto: plain-file backend (`~/.cache/mcp-server-microsoft-tasks/
       <profile>/token.json` mode 0600).
    """
    forced = os.environ.get(STORE_OVERRIDE_ENV, "").strip().lower()
    if forced == "keyring":
        return KeyringTokenStore()
    if forced in ("encrypted-file", "encrypted_file", "encrypted"):
        return EncryptedFileTokenStore()
    if forced == "file":
        return PlainFileTokenStore()
    if forced:
        raise NoUsableTokenStoreError(
            f"{STORE_OVERRIDE_ENV} must be 'keyring', 'file', or 'encrypted-file'; got {forced!r}",
        )

    if is_real_keyring_backend(keyring.get_keyring()):
        return KeyringTokenStore()

    if os.environ.get(PASSPHRASE_ENV):
        return EncryptedFileTokenStore()

    return PlainFileTokenStore()
