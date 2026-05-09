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
