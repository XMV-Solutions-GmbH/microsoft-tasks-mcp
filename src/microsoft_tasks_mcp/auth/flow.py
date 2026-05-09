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

# Env flag that opts the running MCP server out of Planner support
# entirely. When truthy: Group.Read.All is dropped from the OAuth scope
# request (so a non-admin tenant's user can complete sign-in without
# needing tenant-admin consent), and the MCP server skips registering
# any planner_* tools. Useful for users who only care about their
# personal Microsoft To Do tasks.
NO_PLANNER_ENV = "MS_TASKS_NO_PLANNER"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def writes_enabled() -> bool:
    """True iff `TASKS_ALLOW_WRITES` is set to a recognised truthy value.

    Default (unset / empty / anything else): writes are NOT enabled. The
    OAuth scope request omits Tasks.ReadWrite; the consent screen does
    not mention "modify your tasks"; and the MCP server does not register
    the write tools (gated by the same flag in server.py).
    """
    return os.environ.get(ALLOW_WRITES_ENV, "").strip().lower() in _TRUE_VALUES


def planner_disabled() -> bool:
    """True iff `MS_TASKS_NO_PLANNER` is set to a recognised truthy value.

    When True: `Group.Read.All` is dropped from the OAuth scope request,
    Planner tool registration is skipped, and the cross-source tools
    (`tasks_assigned_to_me`, `tasks_search`) silently exclude the
    Planner half. Lets non-admin users in admin-consent-strict tenants
    use the To Do half without their tenant admin needing to grant
    `Group.Read.All`.
    """
    return os.environ.get(NO_PLANNER_ENV, "").strip().lower() in _TRUE_VALUES


def resolve_scopes() -> tuple[str, ...]:
    """Return the OAuth scopes to request at this moment.

    Composition rules (resolved at call time, not module load):

    - Always include `Tasks.Read`, `User.Read`, `offline_access`.
    - Include `Group.Read.All` unless `MS_TASKS_NO_PLANNER` is truthy.
    - Append `Tasks.ReadWrite` when `TASKS_ALLOW_WRITES` is truthy.

    The default install consent screen reads "this app can read your
    tasks" + "read all groups". Setting MS_TASKS_NO_PLANNER drops the
    groups scope; setting TASKS_ALLOW_WRITES adds the writes scope. Both
    flags are independent.
    """
    scopes: list[str] = ["Tasks.Read"]
    if writes_enabled():
        scopes.append("Tasks.ReadWrite")
    if not planner_disabled():
        scopes.append("Group.Read.All")
    scopes.extend(["User.Read", "offline_access"])
    return tuple(scopes)


# Backwards-compat alias so callers who still import DEFAULT_SCOPES at
# module load continue to work — they get the read-only-with-Planner
# default. Tests that need env-aware shape should call resolve_scopes()
# directly.
DEFAULT_SCOPES: tuple[str, ...] = (
    "Tasks.Read",
    "Group.Read.All",
    "User.Read",
    "offline_access",
)
# Internal alias kept for symmetry with old test references.
_BASE_SCOPES = DEFAULT_SCOPES

DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

__all__ = [
    "ALLOW_WRITES_ENV",
    "AUTHORITY_BASE",
    "DEFAULT_AUTHORITY_TENANT",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_SCOPES",
    "DEVICE_CODE_GRANT_TYPE",
    "NO_PLANNER_ENV",
    "AuthorizationDeniedError",
    "CachedToken",
    "DeviceCodeChallenge",
    "DeviceCodeError",
    "DeviceCodeExpiredError",
    "RefreshTokenInvalidError",
    "planner_disabled",
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
