# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Persistent registry of tasks created by this MCP profile.

The load-bearing safety guarantee of v0.2: write tools refuse to act
on any task whose ID is not in the per-profile registry. A
hand-created task in Microsoft To Do or Microsoft Planner will never
have a matching registry entry and is therefore protected from
accidental MCP-side mutation.

Same shape as `mcp-server-outlook`'s `draft_registry.py`. Layout:
`<base_dir>/<profile>/tasks.json` with mode 0o600. Atomic write via
temp-file + rename so a crash mid-write doesn't leave a half-
truncated registry.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

DEFAULT_REGISTRY_DIR = Path.home() / ".cache" / "mcp-server-microsoft-tasks"

# Process-wide lock for registry mutations. Concurrent task creation
# (e.g. agent runs many `*_task_create` calls in flight) does a
# non-atomic read-modify-write (list_all → mutate → _write).
# Held only for the duration of each mutation; underlying I/O is fast.
_REGISTRY_LOCK = threading.Lock()

TaskSource = Literal["todo", "planner"]


@dataclass(frozen=True)
class TaskEntry:
    """One row in the per-profile task registry.

    `source` distinguishes To Do tasks (per-user lists) from Planner
    tasks (group-scoped). `list_or_plan_id` is the To Do list-id or
    the Planner plan-id depending on source. `etag` is the last
    ETag the MCP server saw — write tools attach it via `If-Match`
    so external concurrent edits surface as 412 Precondition Failed
    instead of being silently clobbered.
    """

    source: TaskSource
    graph_id: str
    list_or_plan_id: str
    title: str
    etag: str | None
    created_at: float  # epoch seconds


class TaskRegistry:
    """File-backed registry of tasks created by this profile."""

    def __init__(self, profile: str, base_dir: Path | None = None) -> None:
        self._dir = (base_dir if base_dir is not None else DEFAULT_REGISTRY_DIR) / profile
        self._registry_file = self._dir / "tasks.json"

    def list_all(self) -> list[TaskEntry]:
        """Return every currently-tracked entry. Empty list if none."""
        if not self._registry_file.exists():
            return []
        try:
            raw = json.loads(self._registry_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Corrupt file — treat as empty rather than crash. Caller
            # can delete the registry to recover.
            return []
        return [TaskEntry(**row) for row in raw if isinstance(row, dict)]

    def get(self, graph_id: str) -> TaskEntry | None:
        for entry in self.list_all():
            if entry.graph_id == graph_id:
                return entry
        return None

    def add(self, entry: TaskEntry) -> None:
        """Add or replace the entry for `entry.graph_id`. Thread-safe."""
        with _REGISTRY_LOCK:
            existing = [e for e in self.list_all() if e.graph_id != entry.graph_id]
            existing.append(entry)
            self._write(existing)

    def remove(self, graph_id: str) -> TaskEntry | None:
        """Remove the entry for `graph_id`. Returns the removed entry,
        or None if it wasn't tracked. Thread-safe."""
        with _REGISTRY_LOCK:
            existing = self.list_all()
            match = next((e for e in existing if e.graph_id == graph_id), None)
            if match is None:
                return None
            remaining = [e for e in existing if e.graph_id != graph_id]
            self._write(remaining)
        return match

    def update_etag(self, graph_id: str, etag: str | None) -> None:
        """Update only the ETag for an existing entry. Used after a
        successful PATCH so the next concurrency check uses the fresh
        ETag.

        No-op if the entry isn't tracked (the write tools refuse to
        operate on un-tracked tasks anyway, so this defensive branch
        only hits in tests).
        """
        with _REGISTRY_LOCK:
            existing = self.list_all()
            match = next((e for e in existing if e.graph_id == graph_id), None)
            if match is None:
                return
            updated = TaskEntry(
                source=match.source,
                graph_id=match.graph_id,
                list_or_plan_id=match.list_or_plan_id,
                title=match.title,
                etag=etag,
                created_at=match.created_at,
            )
            remaining = [e for e in existing if e.graph_id != graph_id] + [updated]
            self._write(remaining)

    def _write(self, entries: list[TaskEntry]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix="tasks-",
            suffix=".json.tmp",
            dir=self._dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([asdict(e) for e in entries], f, indent=2)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self._registry_file)
        except OSError:
            try:
                Path(tmp_path).unlink()
            except FileNotFoundError:
                pass
            raise


def now() -> float:
    """Wall-clock epoch seconds; injectable for tests."""
    return time.time()
