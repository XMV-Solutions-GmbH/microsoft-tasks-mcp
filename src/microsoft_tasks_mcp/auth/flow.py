# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""OAuth 2.0 Device Code Flow + refresh-token client against Microsoft Identity.

Thin shim over `mcp-microsoft-graph-auth`'s `device_code` module that
supplies Microsoft-Tasks-specific defaults: the bundled multi-tenant
Entra app's client_id, the Tasks-flavoured Graph scopes, and the
multi-tenant `organizations` authority.

Default scopes are deliberately read-only and DO NOT include
`Tasks.ReadWrite`. The compliance line of this server is "read-only by
default; writes opt-in; never modify tasks the agent did not create
itself" — the consent prompt should never read "this app can modify
your tasks" unless the operator opts in via `TASKS_ALLOW_WRITES`. See
`docs/app-concept.md` § Auth model for the full rationale.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import httpx
from mcp_microsoft_graph_auth.device_code import (
    AUTHORITY_BASE,
    AuthorizationDeniedError,
    DeviceCodeChallenge,
    DeviceCodeError,
    DeviceCodeExpiredError,
    RefreshTokenInvalidError,
)
from mcp_microsoft_graph_auth.device_code import (
    poll_for_token as _lib_poll_for_token,
)
from mcp_microsoft_graph_auth.device_code import (
    refresh_access_token as _lib_refresh_access_token,
)
from mcp_microsoft_graph_auth.device_code import (
    request_device_code as _lib_request_device_code,
)
from mcp_microsoft_graph_auth.tokens import CachedToken

# ---------------------------------------------------------------------
# Microsoft-Tasks-specific defaults — see docs/app-concept.md § Auth model.
# ---------------------------------------------------------------------

# XMV-published multi-tenant Entra app registration for
# mcp-server-microsoft-tasks. Public client, Device Code flow enabled.
# Registered delegated permissions: Tasks.Read, Tasks.ReadWrite,
# Group.Read.All, User.Read, offline_access (admin-consent granted
# tenant-wide in the XMV tenant). **Tasks.ReadWrite is in the registered
# permission list but is NOT in the default OAuth scope request** — see
# `resolve_scopes()` below for the lazy-request semantic.
# Override via TASKS_CLIENT_ID for tenants with strict app-allowlisting.
DEFAULT_CLIENT_ID = "0faf4ede-b330-4034-a49f-cbb47eac0ccd"
DEFAULT_AUTHORITY_TENANT = "organizations"

# Env var that opts the running MCP server into requesting Tasks.ReadWrite
# at OAuth time (and registering the write tools as MCP tools). When
# unset / falsy, the consent screen does NOT include "this app can
# modify your tasks" — the default install is read-only. See
# docs/app-concept.md § "Read-only by default" for the design discussion.
ALLOW_WRITES_ENV = "TASKS_ALLOW_WRITES"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

_BASE_SCOPES: tuple[str, ...] = (
    # Read both To Do (per-user) and Planner (group-scoped) tasks.
    "Tasks.Read",
    # Group.Read.All is required for Planner: plans are tied to M365
    # groups, and we need to enumerate the user's groups via /me/memberOf
    # before we can even list their plans. Admin-consent in most tenants
    # — XMV-tenant grant is tenant-wide.
    "Group.Read.All",
    "User.Read",
    "offline_access",
)


def writes_enabled() -> bool:
    """True iff `TASKS_ALLOW_WRITES` is set to a recognised truthy value.

    Default (unset / empty / anything else): writes are NOT enabled. The
    OAuth scope request omits Tasks.ReadWrite; the consent screen does
    not mention "modify your tasks"; and the MCP server does not register
    the write tools (gated by the same flag in server.py).
    """
    return os.environ.get(ALLOW_WRITES_ENV, "").strip().lower() in _TRUE_VALUES


def resolve_scopes() -> tuple[str, ...]:
    """Return the OAuth scopes to request at this moment.

    Always includes `_BASE_SCOPES`. Appends `Tasks.ReadWrite` only when
    `writes_enabled()` is true — this is the load-bearing property that
    keeps the default install's consent screen read-only while permitting
    an explicit per-deployment opt-in. Resolved at call time, not at
    module load, so test-time `monkeypatch.setenv` flips behaviour
    without re-importing.
    """
    if writes_enabled():
        # Order matches outlook-mcp's pattern: append the optional scope
        # last so the read-only base remains stable.
        return (
            "Tasks.Read",
            "Tasks.ReadWrite",
            "Group.Read.All",
            "User.Read",
            "offline_access",
        )
    return _BASE_SCOPES


# Backwards-compat alias so callers who still import DEFAULT_SCOPES at
# module load continue to work — they get the un-flagged default.
DEFAULT_SCOPES = _BASE_SCOPES

DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

__all__ = [
    "ALLOW_WRITES_ENV",
    "AUTHORITY_BASE",
    "DEFAULT_AUTHORITY_TENANT",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_SCOPES",
    "DEVICE_CODE_GRANT_TYPE",
    "AuthorizationDeniedError",
    "CachedToken",
    "DeviceCodeChallenge",
    "DeviceCodeError",
    "DeviceCodeExpiredError",
    "RefreshTokenInvalidError",
    "poll_for_token",
    "refresh_access_token",
    "request_device_code",
    "resolve_scopes",
    "writes_enabled",
]


def request_device_code(
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] | None = None,
    http: httpx.Client | None = None,
) -> tuple[str, DeviceCodeChallenge]:
    """Initiate the Device Code flow with Tasks-flavoured defaults.

    `scopes=None` (the default) calls `resolve_scopes()` so the env-var-
    aware Tasks.ReadWrite-when-enabled behaviour kicks in. Pass an
    explicit tuple to override.
    """
    return _lib_request_device_code(
        client_id=client_id,
        tenant=tenant,
        scopes=scopes if scopes is not None else resolve_scopes(),
        http=http,
    )


def poll_for_token(
    *,
    device_code: str,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    interval: int = 5,
    http: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> CachedToken:
    """Poll `/token` until the user completes (or denies) sign-in."""
    return _lib_poll_for_token(
        device_code=device_code,
        client_id=client_id,
        tenant=tenant,
        interval=interval,
        http=http,
        sleep=sleep,
        now=now,
    )


def refresh_access_token(
    *,
    refresh_token: str,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] | None = None,
    http: httpx.Client | None = None,
) -> CachedToken:
    """Exchange a refresh token for a new access (and refresh) token.

    Like `request_device_code`, `scopes=None` (the default) calls
    `resolve_scopes()`.
    """
    return _lib_refresh_access_token(
        refresh_token=refresh_token,
        client_id=client_id,
        tenant=tenant,
        scopes=scopes if scopes is not None else resolve_scopes(),
        http=http,
    )
