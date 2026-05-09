# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""mcp-server-microsoft-tasks — MCP server for Microsoft Planner + To Do.

Read-only by default; writes opt-in via TASKS_ALLOW_WRITES=true; never
modifies tasks the agent did not create itself (per-profile registry).

See docs/app-concept.md for the full design.
"""

from __future__ import annotations

__version__ = "0.4.0"
