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
    list_id: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Mark a To Do task this profile created as completed.

    `list_id` is OPTIONAL and only consulted when
    `TASKS_ALLOW_EXTERNAL_WRITES=true` AND the task isn't in this
    profile's registry — Microsoft Graph's To Do API requires the
    list id in the URL. Discover list ids via the `todo_lists` tool.

    Refuses with `NotOwnedByProfileError` if not in registry and
    external-writes is off. Refuses with `ExternalListIdRequiredError`
    if external-writes is on but no `list_id` was provided.
    Refuses with `ExternallyModifiedError` if ETag changed externally.
    """
    return update_todo_task(
        task_id,
        status="completed",
        list_id=list_id,
        profile=profile,
        http=http,
        registry=registry,
    )
