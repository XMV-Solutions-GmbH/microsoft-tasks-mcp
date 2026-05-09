<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Tracked in [GitHub Issues](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues).

## [v0.2.0] — 2026-05-09

Write tools opt-in via `TASKS_ALLOW_WRITES=true`. The load-bearing safety guarantee — the agent never modifies tasks it did not create itself — is enforced by a per-profile on-disk registry and ETag-based optimistic concurrency.

### Added

- **Per-profile task registry** (`src/microsoft_tasks_mcp/task_registry.py`) — JSON-on-disk at `~/.cache/mcp-server-microsoft-tasks/<profile>/tasks.json`, mode 0o600. Atomic temp-file + rename writes, process-wide threading lock for concurrent mutations. Persists across server restarts. Records `source` / `graph_id` / `list_or_plan_id` / `title` / `etag` / `created_at` per entry.
- **`tasks_status`** MCP tool — read-only registry inspection. Returns every task this profile created with last-known title, source, ETag, creation timestamp.
- **To Do write tools** (4):
  - `todo_task_create(list_id, title, body?, due_date?, importance?)` — POST + add to registry.
  - `todo_task_update(task_id, title?, body?, due_date?, status?, importance?)` — PATCH with `If-Match`. Refuses `NOT_OWNED_BY_PROFILE` if not in registry. Refuses `EXTERNALLY_MODIFIED` on 412.
  - `todo_task_complete(task_id)` — convenience wrapper over update with `status="completed"`.
  - `todo_task_delete(task_id)` — idempotent (404 = success, registry cleaned).
- **Planner write tools** (4):
  - `planner_task_create(plan_id, bucket_id, title, body?, due_date?, assignees?)` — POST + add to registry. `body` writes to `/details.description` in a follow-up PATCH (transparent two-Graph-call sequence). `assignees` is M365 user-ids (not UPNs).
  - `planner_task_update(task_id, title?, bucket_id?, due_date?, status?, priority?)` — PATCH with `If-Match`. `status` maps `completed`/`not_completed` to `percentComplete` 100/0. Falls back to a GET when Graph returns 204 instead of representation.
  - `planner_task_complete(task_id)` — convenience wrapper.
  - `planner_task_delete(task_id)` — idempotent with `If-Match`.
- **Shared write-guard module** (`tools/_writes_common.py`): `require_owned_by_profile()` runs **before** any Microsoft Graph call. `NotOwnedByProfileError` and `ExternallyModifiedError` are the two structured failures the agent can act on.
- **Harness write tests**: real Microsoft Graph create / update / complete / delete cycles for both surfaces, with try/finally cleanup so no orphan tasks linger on the live plan.
- **Harness sandbox provisioned**: dedicated M365 group (`Microsoft Tasks MCP Harness`, mailNickname `microsoft-tasks-mcp-harness`) with one Planner plan `Harness` containing `Todo` and `Done` buckets and a seed task. Re-activates the previously-skipped Planner harness reads + lights up the new Planner write harness.

### Changed

- **Default install OAuth scopes are unchanged.** `Tasks.ReadWrite` is appended to the OAuth scope request only when `TASKS_ALLOW_WRITES=true`. The default consent prompt stays read-only.
- **Server registration**: `register_write_tools` now actually registers nine tools (`tasks_status` + 4 todo + 4 planner) when `TASKS_ALLOW_WRITES` is truthy. Without the env flag, the server runs in read-only mode unchanged from v0.1.0.

### Engineering

- 298 unit + integration tests, 16 harness tests against the real Microsoft Graph against the harness account.
- Branch protection enforced on `main` since v0.1.0; every v0.2 chunk shipped as its own PR with green CI.

## [v0.1.0] — 2026-05-09

First public release. Read-only MVP across **Microsoft Planner + Microsoft To Do**, unified.

### Added

- **Auth shim** wrapping [`mcp-microsoft-graph-auth`](https://pypi.org/project/mcp-microsoft-graph-auth/): Device Code flow with `Tasks.Read` + `Group.Read.All` + `User.Read` + `offline_access` by default. Multi-profile support via `TASKS_PROFILE`. Token store auto-picks OS keyring on macOS / Windows / Linux-desktop, plain-file 0600 elsewhere; explicit override via `MS_TASKS_TOKEN_STORE=keyring|file|encrypted-file`. Encrypted-file backend uses `MS_TASKS_TOKEN_PASSPHRASE`. BYO Entra app via `TASKS_CLIENT_ID` / `TASKS_TENANT_ID`. `TASKS_ALLOW_WRITES=true` flips on `Tasks.ReadWrite` at request time (writes themselves land in v0.2).
- **CLI**: `mcp-server-microsoft-tasks login [--profile NAME]`, `... logout [--profile NAME]`, no-subcommand starts the MCP server on stdio. Login prompt format: device code first in its own bare code block, verification URL second on its own line as a plain auto-link — mobile-friendly copy → click → paste.
- **Login MCP tools** (always available, **non-blocking by design**):
  - `tasks_login_begin(force=False)` — returns immediately with `status="pending"` plus `user_code` + `verification_url`; polling task spawned via `asyncio.create_task`. `force=True` cancels in-flight session and atomically replaces it. Idempotent on existing pending sessions.
  - `tasks_login_status()` — three-state active probe (`signed_in` / `pending` / `none`). Tries the TokenStore first (silent refresh if needed); falls through to in-process registry only when no token is obtainable.
- **To Do read tools** (4):
  - `todo_lists(limit=50)` — enumerate the user's To Do lists.
  - `todo_list_get(list_id)` — fetch one list.
  - `todo_tasks(list_id, status_filter="all", limit=100)` — list tasks; `status_filter` maps `"completed"` / `"not_completed"` / `"all"` onto Graph `$filter` clauses.
  - `todo_task_get(list_id, task_id)` — fetch one task. Both ids required (Graph has no global task-by-id endpoint for To Do).
- **Planner read tools** (5):
  - `planner_plans(group_id?, limit=50)` — without `group_id`, enumerates the user's M365 groups via `/me/memberOf` (Group.Read.All — admin consent on the XMV-published app) and aggregates plans across them. With `group_id`, lists plans within that one group. 403 on individual groups is swallowed (a group with Planner disabled shouldn't kill the call).
  - `planner_plan_get(plan_id)` — fetch one plan.
  - `planner_buckets(plan_id)` — list buckets (columns) within a plan.
  - `planner_tasks(plan_id, bucket_id?, status_filter?, limit=100)` — list tasks. `bucket_id` and `status_filter` applied client-side because Planner uses `percentComplete` rather than a status enum.
  - `planner_task_get(task_id, include_details=False)` — fetch one task; `include_details=True` adds description / checklist / references / preview_type via a second `/details` round-trip.
- **Cross-source convenience** (2):
  - `tasks_assigned_to_me(include_completed=False, limit=100)` — unified view of To Do + Planner items currently on the user's plate. Sorted by `due_date` ascending (None last). Per-source budget of `limit // 2` so neither half starves.
  - `tasks_search(query, source="all"|"todo"|"planner", limit=50)` — case-insensitive substring search across `title` and `body_preview`. Client-side because neither surface exposes a server-side `$search` for tasks.
- **Unified task envelope** across both surfaces: `id`, `title`, `status` (`completed` / `not_completed`), `due_date`, `assignees`, `web_url`, `source` (`"todo"` or `"planner"`), `etag`, plus source-specific extras. Agents route follow-up calls off the `source` tag without learning two response shapes.
- **OAuth app + privacy/terms pages** registered + published:
  - Multi-tenant Entra app `mcp-server-microsoft-tasks` (client id `0faf4ede-b330-4034-a49f-cbb47eac0ccd`), public client, Device Code enabled. Tenant-wide admin consent granted in the XMV tenant for `Tasks.Read`, `Tasks.ReadWrite`, `Group.Read.All`, `User.Read`, `offline_access`.
  - Privacy notice live at <https://xmv.de/oss/microsoft-tasks-mcp/privacy>.
  - Terms of use live at <https://xmv.de/oss/microsoft-tasks-mcp/terms>.
- **CI**: three-job shape (lint / test / harness). Lint runs ruff + ruff-format-check + mypy strict + markdownlint. Test runs `pytest` + codecov upload. Harness restores the `MS_TASKS_HARNESS_TOKEN_JSON` repo secret and runs the harness suite against real Microsoft Graph; skips silently when the secret is missing (PRs from forks).
- **Release** via PyPI Trusted Publisher (OIDC) — `uv build` + `uv publish` from the GitHub-hosted `pypi` environment, no long-lived token needed.
- **Tests**: 229 unit + integration tests covering the full v0.1 surface (envelope shape, auth shim, store backend selection, login non-blocking semantics, all 11 read tools, cross-module wiring through the FastMCP server). 11 harness tests hit the real Microsoft Graph against `d.koller@xmv.de`'s harness profile.

### Engineering principles + AGENTS.md

- Dropped in from `oss-project-template` v0.3.0 — `ENGINEERING_PRINCIPLES.md` (project-agnostic baseline) + `AGENTS.md` (this project's overrides + tech stack + login-must-be-non-blocking pin).

### Known gaps (follow-up)

- `web_url` is `None` for both To Do and Planner tasks in v0.1 — the deep-link patterns aren't stable / require tenant context. Wire in v0.2.
- `tasks_search` is client-side because neither Microsoft surface exposes server-side task search. Spike on the Microsoft Graph Search API (`/search/query`) is on the v0.2+ roadmap.
- Harness account `d.koller@xmv.de` currently has no Planner plans visible. Planner harness tests skip defensively. Adding the harness account to a Planner-enabled M365 group would activate the round-trip assertions.

[Unreleased]: https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/compare/v0.2.0...HEAD
[v0.2.0]: https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/releases/tag/v0.2.0
[v0.1.0]: https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/releases/tag/v0.1.0
