# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""tasks_status — list tasks this profile created.

Reads the per-profile task registry (`task_registry.py`) and returns
every entry. The agent uses this to remember what it created so it
can follow up on its own work — and importantly, the same registry
is what the write tools (`*_task_update`, `_complete`, `_delete`)
consult before mutating: only registry-tracked tasks are mutable.

Read-only; does not hit Microsoft Graph. Cheap.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from microsoft_tasks_mcp.task_registry import TaskRegistry


def status(*, profile: str = "default") -> list[dict[str, Any]]:
    """List tasks this profile has created.

    Returns each entry as a dict: `source` (`"todo"` or `"planner"`),
    `graph_id`, `list_or_plan_id`, `title`, `etag`, `created_at`
    (epoch seconds float).

    Empty list when this profile hasn't created anything yet.
    """
    registry = TaskRegistry(profile)
    return [asdict(entry) for entry in registry.list_all()]
