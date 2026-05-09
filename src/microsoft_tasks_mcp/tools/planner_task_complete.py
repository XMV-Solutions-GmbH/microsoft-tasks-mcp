# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_task_complete — mark a profile-owned Planner task as completed.

Convenience wrapper around `planner_task_update(status="completed")`.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools.planner_task_update import update_planner_task


def complete_planner_task(
    task_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Mark a Planner task this profile created as completed."""
    return update_planner_task(
        task_id,
        status="completed",
        profile=profile,
        http=http,
        registry=registry,
    )
