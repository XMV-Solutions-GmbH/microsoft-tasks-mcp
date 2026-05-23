# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""tasks_login_begin — drive the OAuth Device Code flow as an MCP tool.

**Non-blocking** async tool that:

1. Returns the existing in-flight session (idempotent) when one is
   already pending for `profile` and `force=False`.
2. Otherwise initiates a fresh Device Code flow (one HTTP round-trip
   to Microsoft Identity), records a `LoginSession` in the
   process-wide registry, kicks off a background polling task, and
   **returns immediately** with the user-facing fields (`user_code`,
   `verification_url`, etc.) so the agent can surface them.
3. The agent then polls `tasks_login_status` until status flips to
   `signed_in` (or to a terminal `expired` / `failed`).

Non-blocking is mandatory. Blocking would deadlock the UX on clients
that don't render progress notifications (sister project
mcp-server-outlook v0.3.0 incident — fixed in v0.3.1). The pattern
here matches the canonical RFC design and the post-fix
`ol_login_begin` / `sp_login_begin` shape.

`force=True` cancels any in-flight session for the profile and starts
fresh, replacing what would otherwise be a separate cancel tool.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import httpx
from mcp_microsoft_graph_auth import LoginSession, public_view

from microsoft_tasks_mcp.auth import (
    AuthorizationDeniedError,
    DeviceCodeExpiredError,
    LoginAccountTypeRequiredError,
)
from microsoft_tasks_mcp.auth.flow import (
    DEFAULT_CLIENT_ID,
    account_type_to_tenant,
    poll_for_token,
    request_device_code,
)
from microsoft_tasks_mcp.auth.store import get_token_store
from microsoft_tasks_mcp.login_state import cache_upn, get_login_session_registry
from microsoft_tasks_mcp.tools._common import GRAPH_BASE, auth_headers

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

_log = logging.getLogger("microsoft-tasks-mcp.login_begin")


async def login_begin(
    *,
    account_type: str | None = None,
    profile: str = "default",
    force: bool = False,
    ctx: Context[Any, Any] | None = None,
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Drive the Device Code flow. **Returns immediately, non-blocking.**

    `account_type` (#54) MUST be `"personal"` or `"work_or_school"` to
    route the device-code request to the right Microsoft Identity
    authority. If missing, raises `LoginAccountTypeRequiredError` with
    an agent-readable instruction to ask the user. The legacy
    `TASKS_TENANT_ID` env var, if set, satisfies the requirement
    (power-user escape hatch).

    Returns the public-view dict of the resulting `LoginSession` with
    `status="pending"` while polling continues in the background.
    Fields: `session_id`, `user_code`, `verification_url`,
    `verification_url_complete`, `expires_at`, `time_remaining_s`,
    `status`, `signed_in_user_upn`, `error`.

    The agent renders `user_code` first (in a code block, no labels)
    and `verification_url` second (plain auto-link), then polls
    `tasks_login_status` until status flips to `signed_in` or to a
    terminal failure state.

    Idempotent: if a non-expired pending session already exists for
    this profile, the existing session is returned without starting a
    second polling task. Pass `force=True` to cancel the in-flight
    session and start fresh.

    `ctx` is accepted for forward compatibility but currently unused —
    `tasks_login_status` polling covers the use case without the
    asyncio-task-vs-tool-response lifecycle complexity that progress-
    during-blocking-tool-call would entail.
    """
    del ctx  # currently unused — see docstring
    resolved_tenant = _resolve_login_tenant_for_mcp_tool(account_type)
    registry = get_login_session_registry()
    existing = registry.get(profile)

    if existing is not None and existing.status == "pending":
        if force:
            _cancel_session(existing)
            registry.remove(profile)
        else:
            # Idempotent: return the existing pending session unchanged.
            return public_view(existing, now=datetime.now(UTC))

    # Initiate Device Code flow (sync HTTP, sub-second).
    device_code, challenge = await asyncio.to_thread(
        request_device_code,
        client_id=DEFAULT_CLIENT_ID,
        tenant=resolved_tenant,
        http=http,
    )
    started_at = datetime.now(UTC)
    session = LoginSession(
        session_id=str(uuid.uuid4()),
        profile=profile,
        device_code=device_code,
        user_code=challenge.user_code,
        verification_url=challenge.verification_uri,
        verification_url_complete=challenge.verification_uri_complete,
        expires_at=datetime.fromtimestamp(challenge.expires_at, tz=UTC),
        interval_s=challenge.interval,
        status="pending",
        signed_in_user_upn=None,
        error=None,
        task=None,
        started_at=started_at,
    )
    # First-write-wins for two concurrent callers — put_if_absent makes
    # that atomic. If another caller raced, drop our device_code and
    # return their session.
    final = registry.put_if_absent(session)
    if final is not session:
        return public_view(final, now=datetime.now(UTC))

    final.task = asyncio.create_task(_poll_and_finalize(final, tenant=resolved_tenant, http=http))
    return public_view(final, now=datetime.now(UTC))


def _resolve_login_tenant_for_mcp_tool(account_type: str | None) -> str:
    """Resolve the Microsoft Identity tenant path for the MCP tool path.

    Same precedence as `microsoft_tasks_mcp.auth._resolve_login_tenant`
    but inlined here because the MCP tool doesn't take a `tenant=`
    kwarg (would only confuse the agent — the choice between
    `personal` and `work_or_school` covers the legitimate use cases).
    The `TASKS_TENANT_ID` env var stays as a power-user / CI override.
    """
    import os

    if account_type:
        return account_type_to_tenant(account_type)
    env = os.environ.get("TASKS_TENANT_ID", "").strip()
    if env:
        return env
    raise LoginAccountTypeRequiredError


def _cancel_session(session: LoginSession) -> None:
    """Mark a session as cancelled and cancel its polling task."""
    session.status = "cancelled"
    task = session.task
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()


async def _poll_and_finalize(
    session: LoginSession,
    *,
    tenant: str,
    http: httpx.Client | None,
) -> None:
    """Background task: poll Microsoft Identity until a terminal state,
    then write the token + populate the UPN cache.

    `tenant` is the same authority path used for `request_device_code`
    — the `/token` endpoint is per-authority so we have to keep them
    consistent (#54).

    Mutates `session.status`, `session.error`, `session.signed_in_user_upn`
    in place. Persists the token via the configured TokenStore.
    """
    try:
        cached = await asyncio.to_thread(
            poll_for_token,
            device_code=session.device_code,
            client_id=DEFAULT_CLIENT_ID,
            tenant=tenant,
            interval=session.interval_s,
            http=http,
        )
    except AuthorizationDeniedError as exc:
        session.status = "failed"
        session.error = {"code": "access_denied", "message": str(exc)}
        return
    except DeviceCodeExpiredError as exc:
        session.status = "expired"
        session.error = {"code": "expired_token", "message": str(exc)}
        return
    except asyncio.CancelledError:
        # Cancelled (force=True or external cancel) — leave session
        # status alone; _cancel_session has set it to "cancelled".
        raise
    except Exception as exc:
        session.status = "failed"
        session.error = {"code": "unexpected_error", "message": repr(exc)}
        _log.exception("tasks_login_begin polling failed for profile %r", session.profile)
        return

    # Success: persist the token + update the session.
    try:
        store = get_token_store()
        store.set(session.profile, cached.to_json().encode())
    except Exception as exc:
        # Token couldn't be persisted — surface as failure so the agent
        # retries rather than silently moving on.
        session.status = "failed"
        session.error = {"code": "token_store_failed", "message": repr(exc)}
        _log.exception("tasks_login_begin token persist failed for profile %r", session.profile)
        return

    upn = await asyncio.to_thread(_fetch_upn, cached.access_token, http)
    if upn is not None:
        cache_upn(session.profile, upn)
    session.signed_in_user_upn = upn
    session.status = "success"


def _fetch_upn(token: str, http: httpx.Client | None) -> str | None:
    """One sync /me?$select=userPrincipalName round-trip. Defensive
    against wire-format quirks — same shape as login_status._fetch_upn."""
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
