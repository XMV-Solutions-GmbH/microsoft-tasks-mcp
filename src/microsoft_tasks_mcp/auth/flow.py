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
# `common` accepts both AzureAD (work/school) AND personal Microsoft
# accounts (outlook.com / hotmail.com / live.com). The XMV-hosted app
# registration has `signInAudience=AzureADandPersonalMicrosoftAccount`
# since v0.x (personal-account-support PR), so the consent screen lets
# consumer accounts through for the To Do tools. Microsoft Planner is
# work/school-only and the `planner_*` MCP tools guard at call-site
# via `is_personal_account()` — see server.py `_guard_planner_account_type`.
# Multi-tenant B2B is unaffected: `common` is a superset of
# `organizations`.
DEFAULT_AUTHORITY_TENANT = "common"

# Env var that opts the running MCP server into requesting Tasks.ReadWrite
# at OAuth time (and registering the write tools as MCP tools). v0.5
# made this strict — must be exactly `"true"` or `"false"`; unset /
# empty / legacy truthy (`1`/`yes`/`on`) all raise
# `TasksConsentNotConfiguredError` at startup. Rationale: operators
# silently landing in read-only mode without realising writes are a
# separately-opt-in feature was the dominant onboarding failure mode
# in v0.4.x.
ALLOW_WRITES_ENV = "TASKS_ALLOW_WRITES"
_STRICT_TRUE = "true"
_STRICT_FALSE = "false"

# Env flag that opts the running MCP server out of Planner support
# entirely. When truthy: Group.Read.All is dropped from the OAuth scope
# request (so a non-admin tenant's user can complete sign-in without
# needing tenant-admin consent), and the MCP server skips registering
# any planner_* tools. Useful for users who only care about their
# personal Microsoft To Do tasks. v0.5 left this lenient (truthy /
# unset-as-false) because it's a feature-disable toggle, not a
# compliance gate — the default behaviour (Planner enabled) is the
# most-features behaviour.
NO_PLANNER_ENV = "MS_TASKS_NO_PLANNER"
_LENIENT_TRUTHY = frozenset({"1", "true", "yes", "on"})
_TRUE_VALUES = _LENIENT_TRUTHY  # legacy alias for tests


class TasksConsentNotConfiguredError(RuntimeError):
    """Raised at server-build / CLI-login time when `TASKS_ALLOW_WRITES`
    is unset or has a non-`true`/`false` value.

    The exception message is the user-facing onboarding hint —
    callers re-raise without wrapping so the operator sees it
    verbatim on stderr.
    """


# v0.6 (#54): the two valid `account_type` values. Stable contract —
# the strings are emitted in tool descriptions, error messages, CLI
# help, and tests; downstream code matches on them.
ACCOUNT_TYPE_PERSONAL = "personal"
ACCOUNT_TYPE_WORK_OR_SCHOOL = "work_or_school"
VALID_ACCOUNT_TYPES: tuple[str, ...] = (ACCOUNT_TYPE_PERSONAL, ACCOUNT_TYPE_WORK_OR_SCHOOL)


class LoginAccountTypeRequiredError(RuntimeError):
    """Raised when `interactive_login` / `tasks_login_begin` is invoked
    without `account_type` AND no `TASKS_TENANT_ID` env-var override.

    Microsoft Identity's `/common` authority returns the work/school
    Device Code landing page (`https://login.microsoft.com/device`)
    even for apps that accept personal accounts — and that landing page
    rejects personal MSAs. The two options route differently:

    - `account_type="personal"` → `/consumers` authority → personal
      Device Code landing page (`https://www.microsoft.com/link`).
    - `account_type="work_or_school"` → `/organizations` authority →
      work/school Device Code landing page
      (`https://login.microsoft.com/device`).

    There's no way to auto-detect the user's account kind before
    sign-in (we have no identity claim yet), so the caller MUST
    decide. The MCP-tool layer raises this with an agent-readable
    message so the MCP client can ask the user, then retry the tool
    call with the answer.
    """

    AGENT_MESSAGE = (
        "Required parameter `account_type` is missing. "
        "This determines which Microsoft Identity Device Code endpoint "
        "to route to — there is no auto-detection before sign-in.\n\n"
        "Valid values:\n"
        '  "personal"        — outlook.com / hotmail.com / live.com / msn.com '
        "(Microsoft To Do works; Planner does NOT — requires a work/school tenant)\n"
        '  "work_or_school"  — any Microsoft 365 tenant account (incl. B2B guests)\n\n'
        "AGENT_INSTRUCTIONS: Ask the user which Microsoft account they want to sign in "
        "with — a personal Microsoft account (outlook.com / hotmail.com / live.com / "
        "msn.com) or a work/school Microsoft 365 account. Then call this tool again "
        "with the matching account_type value."
    )

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.AGENT_MESSAGE)


def account_type_to_tenant(account_type: str) -> str:
    """Map an `account_type` literal to the Microsoft Identity tenant
    path that returns the correct Device Code landing page.

    - `"personal"` → `"consumers"` (returns `https://www.microsoft.com/link`)
    - `"work_or_school"` → `"organizations"` (returns
      `https://login.microsoft.com/device`)

    Raises `ValueError` for anything else — strict per #54 acceptance
    criteria; we don't want a typo (`account_type="privat"`) to
    silently fall through to a wrong endpoint.

    The legacy `"common"` tenant is intentionally NOT a third option:
    `/common` returns `login.microsoft.com/device` regardless of app
    audience, which broke personal-account sign-in pre-#54. The two
    explicit values let us route correctly per case.
    """
    if account_type == ACCOUNT_TYPE_PERSONAL:
        return "consumers"
    if account_type == ACCOUNT_TYPE_WORK_OR_SCHOOL:
        return "organizations"
    raise ValueError(f"account_type must be one of {VALID_ACCOUNT_TYPES!r}; got {account_type!r}.")


def _strict_bool_env(name: str) -> bool:
    """Read `name` from the environment and parse strictly.

    Returns `True` for "true", `False` for "false" (case-insensitive,
    leading/trailing whitespace ignored). Raises
    `TasksConsentNotConfiguredError` with the documented onboarding-
    help message for anything else, including unset / empty.
    """
    raw = os.environ.get(name)
    if raw is not None:
        normalised = raw.strip().lower()
        if normalised == _STRICT_TRUE:
            return True
        if normalised == _STRICT_FALSE:
            return False
    raise TasksConsentNotConfiguredError(_consent_help_text(name, raw))


def _consent_help_text(name: str, raw: str | None) -> str:
    """Format the onboarding-help message for an unset / invalid
    consent env var."""
    got = "(not set)" if raw is None else f"{raw!r}"
    return (
        f"ERROR: mcp-server-microsoft-tasks requires an explicit "
        f"{ALLOW_WRITES_ENV} decision (got {got}).\n\n"
        f"This server can create / update / complete / delete tasks "
        f"in Microsoft Planner and Microsoft To Do on the signed-in "
        f"user's behalf (opt-in) or operate in read-only mode. There "
        f"is no implicit default — the operator must consciously "
        f"decide.\n\n"
        f"Set in your MCP client config (.mcp.json env section):\n\n"
        f'  "{ALLOW_WRITES_ENV}": "true"    — enable task create / '
        f"update / complete / delete tools\n"
        f'  "{ALLOW_WRITES_ENV}": "false"   — read-only (no write tools)\n\n'
        f'With "false", the OAuth consent screen requests only '
        f'`Tasks.Read`. With "true", it requests `Tasks.ReadWrite` '
        f"instead (subsumes Read). The decision flows through to both "
        f"the tool surface AND the consent prompt.\n\n"
        f"See README §Authentication for the design rationale.\n\n"
        f"The Planner toggle (`MS_TASKS_NO_PLANNER`) and recurrence "
        f"toggle (`MS_TASKS_PLANNER_BETA`) remain lenient (set to a "
        f"truthy value to enable; unset = default off / on respectively)."
    )


def validate_consent_config() -> bool:
    """Validate the consent env var at startup.

    Returns `writes_enabled` (True/False). Raises
    `TasksConsentNotConfiguredError` with a clear, actionable error
    message if `TASKS_ALLOW_WRITES` is unset or has a non-`true`/
    `false` value.
    """
    return _strict_bool_env(ALLOW_WRITES_ENV)


def writes_enabled() -> bool:
    """True iff `TASKS_ALLOW_WRITES` is set to exactly `"true"`.

    Strict parser since v0.5 — raises
    `TasksConsentNotConfiguredError` if the env var is unset, empty,
    or has a value other than `true` or `false`. There is no implicit
    default; the operator must consciously decide. See
    [#37 in outlook-mcp](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/37)
    for the user-side rationale of the same pattern.
    """
    return validate_consent_config()


def planner_disabled() -> bool:
    """True iff `MS_TASKS_NO_PLANNER` is set to a recognised truthy
    value (`"1"`, `"true"`, `"yes"`, `"on"`; case-insensitive).

    Stays **lenient** in v0.5 because this is a feature-disable
    toggle, not a compliance gate — the default behaviour (Planner
    enabled) is the most-features behaviour, not a "did the operator
    consciously decide" question. Setting it to truthy drops
    `Group.Read.All` from the OAuth scope request and skips Planner
    tool registration.
    """
    return os.environ.get(NO_PLANNER_ENV, "").strip().lower() in _LENIENT_TRUTHY


def resolve_scopes() -> tuple[str, ...]:
    """Return the OAuth scopes to request at this moment.

    Composition rules (resolved at call time, not module load):

    - Includes either `Tasks.Read` (writes off) OR `Tasks.ReadWrite`
      (writes on). `Tasks.ReadWrite` subsumes `Tasks.Read`, so we
      replace rather than append — the consent screen on writes-mode
      shows only one tasks line, not two.
    - Include `Group.Read.All` unless `MS_TASKS_NO_PLANNER` is truthy.
    - Always include `User.Read` and `offline_access`.

    Raises `TasksConsentNotConfiguredError` if `TASKS_ALLOW_WRITES`
    is not configured strictly.
    """
    writes = validate_consent_config()
    scopes: list[str] = ["Tasks.ReadWrite"] if writes else ["Tasks.Read"]
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
    "ACCOUNT_TYPE_PERSONAL",
    "ACCOUNT_TYPE_WORK_OR_SCHOOL",
    "ALLOW_WRITES_ENV",
    "AUTHORITY_BASE",
    "DEFAULT_AUTHORITY_TENANT",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_SCOPES",
    "DEVICE_CODE_GRANT_TYPE",
    "NO_PLANNER_ENV",
    "VALID_ACCOUNT_TYPES",
    "AuthorizationDeniedError",
    "CachedToken",
    "DeviceCodeChallenge",
    "DeviceCodeError",
    "DeviceCodeExpiredError",
    "LoginAccountTypeRequiredError",
    "RefreshTokenInvalidError",
    "TasksConsentNotConfiguredError",
    "account_type_to_tenant",
    "planner_disabled",
    "poll_for_token",
    "refresh_access_token",
    "request_device_code",
    "resolve_scopes",
    "validate_consent_config",
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
