# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""MCP tool implementations.

Each tool module exposes one async function that the FastMCP server in
`microsoft_tasks_mcp.server` registers as a tool. Tools follow the
naming convention from `docs/app-concept.md`:

- `tasks_login_begin`, `tasks_login_status` (login)
- `todo_*` (Microsoft To Do)
- `planner_*` (Microsoft Planner)
- `tasks_*` (cross-source convenience)
"""

from __future__ import annotations
