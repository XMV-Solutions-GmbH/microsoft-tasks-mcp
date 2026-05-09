# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared helpers across tool modules.

Default Microsoft Graph base URL + utilities for building the auth
header. Tasks are user-scoped (To Do) or M365-Group-scoped (Planner),
both reachable from `/me/...` or `/groups/{id}/...` against the
signed-in user.

Every Graph request carries a `User-Agent: mcp-server-microsoft-
tasks/<version>` header. ClientAppId + AppDisplayName already identify
the calling app in audit logs; the User-Agent makes raw Graph
diagnostics + traffic captures readable too.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from microsoft_tasks_mcp import __version__

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
USER_AGENT = f"mcp-server-microsoft-tasks/{__version__}"


def auth_headers(token: str) -> dict[str, str]:
    """Build the standard headers for Graph requests.

    Includes the bearer token and a self-identifying User-Agent. Every
    tool routes its outbound HTTP through here, so the audit-trail
    label is consistent.
    """
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }


def tenant_id_from_token(token: str) -> str | None:
    """Extract the `tid` (tenant id GUID) claim from a Microsoft Identity
    JWT access token.

    Returns the GUID string on success, None on any parse failure. Does
    NOT verify the signature — we only consume tokens we just received
    from the trusted token endpoint, so verifying the signature would
    add complexity without value (the access token is already used as
    a bearer credential against Graph).

    Used by the Planner tools to build deep-link URLs of the form
    `https://tasks.office.com/{tid}/Home/Task/{taskId}` without
    needing an extra `/me` round-trip.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    # JWT uses base64url without padding; pad before decoding.
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload: Any = json.loads(payload_bytes)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    tid = payload.get("tid")
    return tid if isinstance(tid, str) and tid else None


def planner_web_url(tenant_id: str, task_id: str) -> str:
    """Build the canonical Planner deep-link for a task.

    Format: `https://tasks.office.com/{tenant_id}/Home/Task/{task_id}`.
    Microsoft accepts both the tenant GUID and the verified domain in
    that segment; we prefer the GUID because it's stable across domain
    rebrands and doesn't require an extra `/me` lookup.
    """
    return f"https://tasks.office.com/{tenant_id}/Home/Task/{task_id}"
