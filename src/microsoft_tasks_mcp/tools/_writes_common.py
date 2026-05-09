# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared error types + helpers for the v0.2 write tools.

The load-bearing safety check — `require_owned_by_profile` — is the
gate every mutating tool runs *before* it makes any Microsoft Graph
call. If the task isn't in this profile's registry, the tool raises
`NotOwnedByProfileError` and never touches Graph.
"""

from __future__ import annotations

from microsoft_tasks_mcp.task_registry import TaskEntry, TaskRegistry


class NotOwnedByProfileError(RuntimeError):
    """Raised when a write tool is asked to act on a task that this
    profile's registry doesn't track.

    Surfaces to the agent as a clear error rather than silently
    succeeding (Graph would happily mutate any task the user has
    permission for; this guard is what makes "agent never modifies
    tasks created by humans or other agents" load-bearing).
    """

    def __init__(self, source: str, graph_id: str) -> None:
        super().__init__(
            f"NOT_OWNED_BY_PROFILE: task {graph_id!r} (source={source!r}) "
            "is not in this MCP profile's created-by-me registry. The "
            "MCP server refuses to update / complete / delete tasks "
            "it did not create itself.",
        )
        self.source = source
        self.graph_id = graph_id


class ExternallyModifiedError(RuntimeError):
    """Raised when Microsoft Graph rejects a write because the task's
    ETag changed externally between the agent's read and write.

    Surfaces as `EXTERNALLY_MODIFIED` so the agent can re-fetch and
    decide whether to retry with the new state."""

    def __init__(self, graph_id: str) -> None:
        super().__init__(
            f"EXTERNALLY_MODIFIED: task {graph_id!r} was modified "
            "externally between read and write. Re-fetch via the "
            "matching `_task_get` tool and decide whether to retry.",
        )
        self.graph_id = graph_id


def require_owned_by_profile(
    *,
    registry: TaskRegistry,
    graph_id: str,
    expected_source: str,
) -> TaskEntry:
    """Raise `NotOwnedByProfileError` if `graph_id` isn't in the registry.

    Returns the existing entry on success. Used by every write tool
    before it makes any Microsoft Graph call — the guard is at the
    tool layer, not at Graph, so even a mis-scoped attempt is caught.
    """
    entry = registry.get(graph_id)
    if entry is None or entry.source != expected_source:
        raise NotOwnedByProfileError(expected_source, graph_id)
    return entry
