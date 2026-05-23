# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""tasks_login_status — three-state active-probe of this profile's auth.

Three states the agent can act on directly:

- `signed_in`: a valid token exists for `profile` (in OS keyring or on
  disk), regardless of how it got there. Includes the case where the
  user logged in via the CLI (`mcp-server-microsoft-tasks login
  --profile <name>`) hours or days ago. The status check actively
  probes the token store + refreshes if needed; it does NOT require
  an in-process LoginSession.
- `pending`: an in-flight Device Code session exists for this profile
  (started by `tasks_login_begin`). The response includes `user_code`,
  `verification_url`, and `time_remaining_s` so the agent can
  re-display the prompt to the user.
- `none`: no token, no in-flight session. The agent should call
  `tasks_login_begin`.

If a previous session terminated unsuccessfully (`failed`, `expired`,
or `cancelled`), the response is `none` plus a structured `error`
field. Successful sessions report `signed_in` — the active probe
finds the freshly-written token.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import httpx
from mcp_microsoft_graph_auth import public_view

from microsoft_tasks_mcp.auth import AuthRequiredError, get_token
from microsoft_tasks_mcp.auth.flow import (
    ALLOW_EXTERNAL_WRITES_ENV,
    ALLOW_WRITES_ENV,
    TasksConsentNotConfiguredError,
    external_writes_enabled,
    writes_enabled,
)
from microsoft_tasks_mcp.login_state import (
    cache_upn,
    cached_upn,
    get_login_session_registry,
)
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers


def _available_flags(*, writes_on: bool, ext_writes_on: bool) -> dict[str, str]:
    """Onboarding block: list every consent gate the agent might need to
    flip, with a one-line description. Content adapts based on which
    flags are already on so the agent doesn't get told to set something
    that's already set.

    Always present in the `tasks_status` response so a naive MCP client
    that has never seen the docs can discover the full opt-in surface
    in-band, without round-tripping to README or app-concept.md.
    """
    if writes_on:
        writes_line = "(already enabled)"
    else:
        writes_line = (
            "Set to 'true' to enable task creation, update, completion, "
            "and deletion. Adds Tasks.ReadWrite to the OAuth scope "
            "(operator must consent at next sign-in)."
        )
    if ext_writes_on:
        ext_writes_line = "(already enabled)"
    else:
        ext_writes_line = (
            f"Set to 'true' (requires {ALLOW_WRITES_ENV}=true) to allow "
            f"the write tools to act on tasks NOT created by this MCP "
            f"profile (e.g. tasks the user typed manually in the To Do "
            f"app). Default behaviour refuses with NOT_OWNED_BY_PROFILE."
        )
    return {
        ALLOW_WRITES_ENV: writes_line,
        ALLOW_EXTERNAL_WRITES_ENV: ext_writes_line,
    }


def _consent_state() -> tuple[bool, bool]:
    """Resolve (writes_enabled, external_writes_enabled) without raising.

    The strict env-var parsers raise `TasksConsentNotConfiguredError`
    when unset or invalid; for the status response we degrade those to
    `False` so the response stays useful as the discovery surface even
    on a half-configured install. The agent reads `available_flags` to
    figure out what to set next.
    """
    try:
        writes_on = writes_enabled()
    except TasksConsentNotConfiguredError:
        writes_on = False
    try:
        ext_writes_on = external_writes_enabled()
    except TasksConsentNotConfiguredError:
        ext_writes_on = False
    return writes_on, ext_writes_on


def login_status(
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return the current auth status for `profile`.

    Active probe semantics: tries to obtain a valid token from the
    configured TokenStore. If that succeeds (cache hit, possibly after
    a silent refresh), reports `signed_in`. Only falls through to the
    in-process `LoginSessionRegistry` lookup when the token probe says
    "no usable credentials".
    """
    # 1. Active probe: try to get a usable token.
    try:
        token = get_token(profile)
    except AuthRequiredError:
        token = None

    writes_on, ext_writes_on = _consent_state()
    onboarding: dict[str, Any] = {
        "writes_enabled": writes_on,
        "external_writes_enabled": ext_writes_on,
        "available_flags": _available_flags(writes_on=writes_on, ext_writes_on=ext_writes_on),
    }

    if token is not None:
        upn = cached_upn(profile)
        if upn is None:
            upn = _fetch_upn(token=token, http=http)
            if upn is not None:
                cache_upn(profile, upn)
        return {
            "status": "signed_in",
            "signed_in_user_upn": upn,
            **onboarding,
        }

    # 2. No token. Check the in-process LoginSessionRegistry.
    registry = get_login_session_registry()
    session = registry.get(profile)
    if session is None:
        return {"status": "none", **onboarding}

    view = public_view(session, now=datetime.now(UTC))

    if session.status == "pending":
        return {
            "status": "pending",
            "session_id": view["session_id"],
            "user_code": view["user_code"],
            "verification_url": view["verification_url"],
            "verification_url_complete": view["verification_url_complete"],
            "expires_at": view["expires_at"],
            "time_remaining_s": view["time_remaining_s"],
            **onboarding,
        }

    # Terminal states: failed / expired / cancelled. (success is
    # impossible to reach here because the active probe above would
    # have found the token first.) Surface as `none` for the agent's
    # decision logic ("call login_begin"), with the underlying error
    # for diagnostics.
    error: dict[str, Any] | None = None
    if session.status in ("failed", "expired", "cancelled"):
        if session.error is not None:
            error = dict(session.error)
        else:
            error = {
                "code": session.status,
                "message": _default_error_message(session.status),
            }
    return {
        "status": "none",
        "previous_session_status": session.status,
        "error": error,
        **onboarding,
    }


def _fetch_upn(*, token: str, http: httpx.Client | None) -> str | None:
    """Round-trip /me?$select=userPrincipalName to learn who the token
    belongs to. Returns None on any failure (network blip, 4xx,
    malformed JSON) — the status response is still useful without the
    UPN. We do at most one of these per profile-state-transition
    because of `cache_upn`."""
    client = http if http is not None else httpx.Client(timeout=15.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me",
            headers=auth_headers(token),
            params={"$select": "userPrincipalName"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        upn = payload.get("userPrincipalName")
        return cast("str | None", upn) if isinstance(upn, str) else None
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if http is None:
            client.close()


def _default_error_message(status: str) -> str:
    return {
        "failed": "the previous login attempt failed before completion",
        "expired": "the device code expired before sign-in completed",
        "cancelled": "the previous login attempt was cancelled (force=True)",
    }.get(status, status)
