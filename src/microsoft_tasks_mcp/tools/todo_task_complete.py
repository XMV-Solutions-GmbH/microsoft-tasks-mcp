# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""todo_task_complete — mark a profile-owned To Do task as completed.

Convenience wrapper around `todo_task_update(status="completed")`.
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools.todo_task_update import update_todo_task


def complete_todo_task(
    task_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Mark a To Do task this profile created as completed.

    Refuses with `NotOwnedByProfileError` if not in registry.
    Refuses with `ExternallyModifiedError` if ETag changed externally.
    """
    return update_todo_task(
        task_id,
        status="completed",
        profile=profile,
        http=http,
        registry=registry,
    )
