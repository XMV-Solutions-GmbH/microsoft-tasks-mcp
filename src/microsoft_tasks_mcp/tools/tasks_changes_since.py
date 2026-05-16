# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""tasks_changes_since — incremental diff of Planner tasks since last poll.

Polls Microsoft Graph for Planner tasks, diffs against an on-disk cursor,
and returns added / modified / removed sets.

Three scope kinds are supported:

- ``{"kind": "plan", "plan_id": "..."}`` — all tasks in one plan via
  ``GET /planner/plans/{id}/tasks``.
- ``{"kind": "assigned_to_me"}`` — tasks assigned to the signed-in user
  via ``GET /me/planner/tasks``.
- ``{"kind": "registry"}`` — one ``GET /planner/tasks/{id}`` per task id
  in the on-disk task registry for the profile.

Cursor file: ``~/.cache/mcp-server-microsoft-tasks/<profile>/cursors.json``,
mode 0o600. Keyed by the sha256 hex of the JSON-serialised scope dict
(sort_keys=True). Per entry: ``{"last_modified_max": "ISO8601 or null",
"seen_ids": ["id1", ...]}``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.task_registry import DEFAULT_REGISTRY_DIR, TaskRegistry
from microsoft_tasks_mcp.tools._common import auth_headers, graph_planner_base, tenant_id_from_token
from microsoft_tasks_mcp.tools._shape import planner_envelope

_VALID_SCOPE_KINDS = frozenset({"plan", "assigned_to_me", "registry"})


# ---------------------------------------------------------------------------
# Cursor store
# ---------------------------------------------------------------------------


class CursorStore:
    """File-backed cursor store for tasks_changes_since.

    The file lives at ``<base_dir>/<profile>/cursors.json`` and is keyed
    by scope-hash strings. Writes are atomic (temp-file + rename) and the
    file is created with mode 0o600 on first write.
    """

    def __init__(self, profile: str, base_dir: Path | None = None) -> None:
        self._dir = (base_dir if base_dir is not None else DEFAULT_REGISTRY_DIR) / profile
        self._path = self._dir / "cursors.json"

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix="cursors-",
            suffix=".json.tmp",
            dir=self._dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self._path)
        except OSError:
            try:
                Path(tmp_path).unlink()
            except FileNotFoundError:
                pass
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope_key(scope: dict[str, Any]) -> str:
    """Return the sha256 hex of the JSON-serialised scope (sort_keys=True)."""
    serialised = json.dumps(scope, sort_keys=True)
    return hashlib.sha256(serialised.encode()).hexdigest()


def _fetch_plan_tasks(
    plan_id: str,
    *,
    client: httpx.Client,
    token: str,
    tenant_id: str | None,
    max_results: int,
) -> list[dict[str, Any]]:
    response = client.get(
        f"{graph_planner_base()}/planner/plans/{plan_id}/tasks",
        headers=auth_headers(token),
    )
    response.raise_for_status()
    raw = response.json().get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for task in raw:
        if len(out) >= max_results:
            break
        if isinstance(task, dict):
            out.append(planner_envelope(task, tenant_id=tenant_id))
    return out


def _fetch_assigned_to_me_tasks(
    *,
    client: httpx.Client,
    token: str,
    tenant_id: str | None,
    max_results: int,
) -> list[dict[str, Any]]:
    response = client.get(
        f"{graph_planner_base()}/me/planner/tasks",
        headers=auth_headers(token),
    )
    response.raise_for_status()
    raw = response.json().get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for task in raw:
        if len(out) >= max_results:
            break
        if isinstance(task, dict):
            out.append(planner_envelope(task, tenant_id=tenant_id))
    return out


def _fetch_registry_tasks(
    profile: str,
    *,
    client: httpx.Client,
    token: str,
    tenant_id: str | None,
    base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Fetch one task per registry entry via GET /planner/tasks/{id}.

    Tasks whose Graph GET returns a 4xx are silently skipped — a 404
    means the task was deleted externally; the diff logic will surface
    it as ``removed`` because its id won't appear in the response set.
    """
    registry = TaskRegistry(profile, base_dir=base_dir)
    entries = [e for e in registry.list_all() if e.source == "planner"]
    out: list[dict[str, Any]] = []
    for entry in entries:
        try:
            resp = client.get(
                f"{graph_planner_base()}/planner/tasks/{entry.graph_id}",
                headers=auth_headers(token),
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            continue
        task_raw = resp.json()
        if isinstance(task_raw, dict):
            out.append(planner_envelope(task_raw, tenant_id=tenant_id))
    return out


def _iso_max(a: str | None, b: str | None) -> str | None:
    """Return the lexicographically larger of two ISO 8601 strings.

    ISO 8601 strings in the form Graph uses (``YYYY-MM-DDTHH:MM:SSZ``)
    sort correctly as plain strings, so string comparison is sufficient.
    None sorts below any real timestamp.
    """
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


# ---------------------------------------------------------------------------
# Main implementation
# ---------------------------------------------------------------------------


def changes_since(
    scope: dict[str, Any],
    profile: str = "default",
    max_results: int = 200,
    http: httpx.Client | None = None,
    *,
    _cursor_base_dir: Path | None = None,
    _registry_base_dir: Path | None = None,
) -> dict[str, Any]:
    """Diff Planner tasks against the on-disk cursor for ``scope``.

    Returns ``{"added": [...], "modified": [...], "removed": [...],
    "cursor_advanced": bool}``.

    ``_cursor_base_dir`` and ``_registry_base_dir`` are injection points
    for tests; production callers leave them None.
    """
    kind = scope.get("kind")
    if kind not in _VALID_SCOPE_KINDS:
        raise ValueError(
            f"scope.kind must be one of {sorted(_VALID_SCOPE_KINDS)}, got {kind!r}"
        )
    if max_results <= 0:
        raise ValueError(f"max_results must be positive, got {max_results}")

    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        if kind == "plan":
            plan_id = scope.get("plan_id")
            if not isinstance(plan_id, str) or not plan_id.strip():
                raise ValueError("scope.plan_id must be a non-empty string for kind='plan'")
            fetched = _fetch_plan_tasks(
                plan_id.strip(),
                client=client,
                token=token,
                tenant_id=tenant_id,
                max_results=max_results,
            )
        elif kind == "assigned_to_me":
            fetched = _fetch_assigned_to_me_tasks(
                client=client,
                token=token,
                tenant_id=tenant_id,
                max_results=max_results,
            )
        else:
            fetched = _fetch_registry_tasks(
                profile,
                client=client,
                token=token,
                tenant_id=tenant_id,
                base_dir=_registry_base_dir,
            )
    finally:
        if http is None:
            client.close()

    return _compute_diff(
        scope=scope,
        fetched=fetched,
        profile=profile,
        cursor_base_dir=_cursor_base_dir,
    )


def _compute_diff(
    scope: dict[str, Any],
    fetched: list[dict[str, Any]],
    profile: str,
    cursor_base_dir: Path | None,
) -> dict[str, Any]:
    store = CursorStore(profile, base_dir=cursor_base_dir)
    all_cursors = store.load()
    key = _scope_key(scope)
    cursor_entry: dict[str, Any] = all_cursors.get(key) or {}
    last_modified_max: str | None = cursor_entry.get("last_modified_max") or None
    seen_ids: set[str] = set(cursor_entry.get("seen_ids") or [])

    fetched_by_id: dict[str, dict[str, Any]] = {}
    for envelope in fetched:
        task_id = envelope.get("id")
        if isinstance(task_id, str) and task_id:
            fetched_by_id[task_id] = envelope

    first_call = not cursor_entry

    added: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []

    new_last_modified_max = last_modified_max
    for task_id, envelope in fetched_by_id.items():
        lm: str | None = envelope.get("last_modified_date_time")
        if isinstance(lm, str) and lm:
            new_last_modified_max = _iso_max(new_last_modified_max, lm)

        if first_call:
            added.append(envelope)
        elif task_id not in seen_ids:
            added.append(envelope)
        elif (
            last_modified_max is not None
            and isinstance(lm, str)
            and lm > last_modified_max
        ):
            modified.append(envelope)

    removed: list[dict[str, Any]] = []
    if not first_call:
        for missing_id in seen_ids - fetched_by_id.keys():
            removed.append({"id": missing_id, "last_known_title": None})

    cursor_advanced = bool(
        added or modified or removed or new_last_modified_max != last_modified_max
    )

    new_seen_ids = sorted(fetched_by_id.keys())
    all_cursors[key] = {
        "last_modified_max": new_last_modified_max,
        "seen_ids": new_seen_ids,
    }
    store.save(all_cursors)

    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "cursor_advanced": cursor_advanced,
    }
