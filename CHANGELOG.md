<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Tracked in [GitHub Issues](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues).

### Added

- **`account_type` parameter on the login surface** (CLI `--account-type` and MCP tool `tasks_login_begin`) with two values: `"personal"` (outlook.com / hotmail.com / live.com / msn.com — To Do works, Planner refuses) and `"work_or_school"` (M365 tenant accounts incl. B2B guests — both work). The MCP tool description and the `LoginAccountTypeRequiredError` message both carry an `AGENT_INSTRUCTIONS:` marker so MCP clients can pattern-match the elicit-the-user UX. Closes [#54](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/54).
- **`account_type_to_tenant(account_type)`** helper exported from `microsoft_tasks_mcp.auth.flow` — maps `"personal"`→`"consumers"`, `"work_or_school"`→`"organizations"`. Strict (`ValueError` on typo).
- **`LoginAccountTypeRequiredError`** exception with a default agent-readable message naming both valid values and the Planner-needs-work/school caveat verbatim.
- **Personal Microsoft accounts supported for the To Do half.** The XMV-hosted Entra app's `signInAudience` was widened from `AzureADMultipleOrgs` to `AzureADandPersonalMicrosoftAccount`. The `todo_*` tools (Microsoft To Do) work on both account types. The `planner_*` tools refuse personal accounts client-side with a clear message since Planner requires an M365 Group (a work/school-only construct).
- **`microsoft_tasks_mcp.auth.is_personal_account(token)`** + **`signed_in_account_type(token)`** — detectors that recognise BOTH JWT-shape tokens with consumer `tid` AND Microsoft Graph opaque tokens (`EwBI…`/`EwBY…`) as personal.
- **`server._guard_planner_account_type(profile)`** — runtime guard called from the top of every `planner_*` MCP-tool wrapper. Raises `PermissionError` with a message naming the `todo_*` alternative when the signed-in account is consumer.
- **Harness profile `harness-personal`** — separate token cache + matching `MS_TASKS_HARNESS_PERSONAL_TOKEN_JSON` repo secret. `ci.yml` restores both caches; personal-account harness tests skip silently if the personal secret is absent. `scripts/renew-harness-token.sh` takes a profile arg (`harness` → `--account-type work_or_school`, `harness-personal` → `--account-type personal`) — no more env-var hacks.

- **`tasks_changes_since(scope, max_results)`** — new MCP tool (closes #41). Polls Microsoft Graph for Planner tasks and diffs against an on-disk cursor, returning `{"added": [...], "modified": [...], "removed": [...], "cursor_advanced": bool}`. Three scope kinds: `{"kind": "plan", "plan_id": "..."}` (all tasks in one plan), `{"kind": "assigned_to_me"}` (tasks assigned to the signed-in user), `{"kind": "registry"}` (one GET per task id in the profile's task registry). Cursor file lives at `~/.cache/mcp-server-microsoft-tasks/<profile>/cursors.json` (mode 0o600), keyed by sha256 of the JSON-serialised scope. Writes are atomic (temp-file + rename). First call returns everything as `added`; subsequent calls return only what changed since the last poll. `last_modified_max` is monotonic — a stale Graph timestamp never rolls the cursor back.

### Changed

- **`is_personal_account()` recognises Microsoft Graph opaque tokens** (`EwBI…` / `EwBY…`) as personal. Pre-v0.6 it returned `False` for opaque tokens — that classified real personal MSA sign-ins as "work/school" and silently bypassed the `_guard_planner_account_type` runtime check. Fix: any non-empty non-3-segment access token is now treated as personal; empty strings and unparseable 3-segment tokens still default to work/school for malformed-input safety.
- **Device Code authority routing**: `interactive_login` / `tasks_login_begin` now route via `/consumers` for personal accounts and `/organizations` for work/school. Microsoft Identity's `/common` was previously the default but returns the work/school landing page (`login.microsoft.com/device`) even for personal-capable apps — that page rejects personal MSAs. The new routing fixes personal-account sign-in end-to-end without requiring per-user env vars.

### Deprecated

- `TASKS_TENANT_ID` env var remains supported as a power-user / CI escape hatch but is no longer the recommended way to pick the Device Code authority. Use `--account-type` (CLI) or the `account_type` MCP-tool parameter instead.

## [v0.5.0] — 2026-05-12

**Breaking change** to the consent-env-var contract — same pattern as `outlook-mcp` v0.4.0 (issue #37 in that repo) and `sharepoint-mcp` v0.5.0. Operators upgrading from v0.4.x must update their `.mcp.json` to set `TASKS_ALLOW_WRITES` to exactly `"true"` or `"false"`; legacy truthy values (`1`, `yes`, `on`) and unset / empty are now rejected at startup. Plus the OAuth consent screen now reflects the operator's actual decision — with `TASKS_ALLOW_WRITES=false` the prompt requests `Tasks.Read` only; with `=true` it requests `Tasks.ReadWrite` (which subsumes Read) instead.

### Changed (breaking)

- **`TASKS_ALLOW_WRITES` must be set to exactly `"true"` or `"false"`** (case-insensitive, trimmed). Any other value — including unset / empty / legacy `1`/`yes`/`on` — causes the server (and the CLI `login` subcommand) to refuse to start with a formatted onboarding-help message printed to stderr. The motivation matches the outlook-mcp issue #37 user-side rationale: operators silently landing in read-only mode without realising writes were a separately-opt-in feature was the dominant onboarding failure mode in v0.4.x.
- **OAuth scopes now respect the consent decision and replace, don't append.** With `TASKS_ALLOW_WRITES=false`, `resolve_scopes()` requests `Tasks.Read`. With `=true`, `Tasks.ReadWrite` REPLACES `Tasks.Read` (ReadWrite subsumes Read; the consent screen now shows one tasks line, not two). Previously the OAuth request appended `Tasks.ReadWrite` to the existing `Tasks.Read` whenever writes were enabled — which displayed two adjacent consent lines and was inconsistent with how the read variant gets used.
- **Server start is no longer silently read-only** when consent is unset. Previously the server fell through to read-only mode with an INFO log; operators commonly missed the log and assumed writes were broken. The new error message is itself the documentation.

### Unchanged on purpose

- **`MS_TASKS_NO_PLANNER` remains lenient** (truthy / unset-as-false). This is a feature-disable toggle, not a compliance gate — the default behaviour (Planner enabled) is the most-features behaviour. Forcing operators to consciously decide between Planner-on and Planner-off would be over-pedantic.
- **`MS_TASKS_PLANNER_BETA` remains lenient** for the same reason — opt-in to /beta endpoints is by definition advanced-mode.

### Added

- **`microsoft_tasks_mcp.auth.flow.TasksConsentNotConfiguredError`** — new exception class raised by the strict consent parser. Re-exported from `auth.flow.__all__` so downstream tooling can catch it.
- **`microsoft_tasks_mcp.auth.flow.validate_consent_config()`** — returns `writes_enabled` (True/False) or raises. Single source of truth; called from `_build_server()` at module import and from `cli.main()` before the login flow.

### Engineering

- 421 unit tests (was 391; +30 new). Strict env-var parser, scope-replacement instead of append, server-build refusal, CLI gating.
- New harness test file `tests/harness/test_consent_gate.py` — 7 end-to-end checks against the real harness profile (skips gracefully if no token cached).

### Migration from v0.4.x

Add the explicit decision to your `.mcp.json` env section:

```jsonc
{
  "mcpServers": {
    "microsoft-tasks": {
      "command": "uvx",
      "args": ["mcp-server-microsoft-tasks"],
      "env": {
        "TASKS_ALLOW_WRITES": "false"   // read-only (no create/update/complete/delete)
        // or
        // "TASKS_ALLOW_WRITES": "true"   // enables planner_task_create, todo_task_create, etc.
        // MS_TASKS_NO_PLANNER and MS_TASKS_PLANNER_BETA stay lenient — set them only if needed.
      }
    }
  }
}
```

If you were already setting `TASKS_ALLOW_WRITES=true` in v0.4.x, no change is needed. If you relied on legacy `1`/`yes`/`on`, change to `true`.

**OAuth re-consent:** the first time the server starts under v0.5 with `TASKS_ALLOW_WRITES=false`, the next login will request `Tasks.Read` only. Existing cached tokens from v0.4 keep working — Graph accepts the broader-scope token even when the client requests narrower scopes on the next refresh.

## [v0.4.0] — 2026-05-09

Three new feature areas (recurrence, references, cross-tenant fan-out) plus an accepted RFC for change notifications. Two new env flags (`MS_TASKS_PLANNER_BETA` for recurrence opt-in; nothing else mandatory) and one breaking shape change on `tasks_assigned_to_me`.

### Added

- **Planner recurrence (read + write), opt-in via `MS_TASKS_PLANNER_BETA=true`.** Microsoft Graph's Planner recurrence APIs (`plannerTaskRecurrence` + `plannerRecurrenceSchedule`) are `/beta`-only as of this release; setting `MS_TASKS_PLANNER_BETA=true` switches every Planner tool from `/v1.0/planner/...` to `/beta/planner/...`. With the flag on, `planner_task_create` and `planner_task_update` accept an optional `recurrence` argument (`{"schedule": {"pattern": ..., "patternStartDateTime": ...}}`) that's forwarded to Graph; the unified envelope surfaces a new `recurrence` key (schedule + series-tracking metadata) on read. Pattern enums (`type`, `daysOfWeek`, `firstDayOfWeek`, `index`) are validated locally before the HTTP call. To stop a series, pass `recurrence={"schedule": null}` (Graph rejects setting top-level `recurrence` to null on tasks that already have it). Closes [#35](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/35).
- **Two new write tools — `planner_task_add_reference` / `planner_task_remove_reference`.** Attach an HTTP/HTTPS URL (typical use cases: OneNote pages, SharePoint docs, web pages) to a profile-owned Planner task; remove it later. Both tools merge into Graph's `plannerTaskDetails.references` open-type dict via PATCH with `If-Match` (the details ETag is independent of the task ETag, fetched in the same call). The same `NOT_OWNED_BY_PROFILE` registry guard and `EXTERNALLY_MODIFIED` ETag-mismatch handling that the existing v0.2 write tools have. URLs are percent-encoded for OData on the wire and decoded back to the canonical form on read, so the agent never sees the encoded key. The `@odata.type` discriminator was empirically validated against the harness — Graph's published docs example shows the wrong type name (`microsoft.graph.externalReference`); the actually-accepted form is `#microsoft.graph.plannerExternalReference`. Closes [#37](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/37).
- **Cross-tenant unified view on `tasks_assigned_to_me`.** New optional `profiles=[...]` argument fans the call out across multiple signed-in tenants and merges into one envelope-list, with each entry tagged with its source `profile`. Per-profile failures (expired token, 403 from a tenant without `Group.Read.All`, transient 5xx) are best-effort skipped — the response now returns `{"tasks": [...], "_skipped_profiles": [...]}` instead of a bare list. RFC: [`docs/proposals/2026-05-09-cross-tenant-unified-view.md`](docs/proposals/2026-05-09-cross-tenant-unified-view.md). Closes [#39](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/39).
- **RFC `docs/proposals/2026-05-09-planner-change-notifications.md` — Accepted (poll-based).** Real Graph webhook subscriptions need a public HTTPS endpoint, which clashes with the locally-installed-on-laptop shape of the MCP. The RFC accepts a poll-based `tasks_changes_since` design for v0.5 and explains why webhook support is deferred to a companion package. Implementation tracked in [#41](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/41).
- **Helper `tools/_common.graph_planner_base()`** — returns `/v1.0` or `/beta` based on `MS_TASKS_PLANNER_BETA`. All Planner tool callers use it instead of the v1.0-hardcoded `GRAPH_BASE`.
- **Helper `tools/_writes_common.validate_planner_recurrence`** — pre-HTTP validation of the `plannerTaskRecurrence` shape. Catches obvious enum mistakes locally; defers richer "type X requires fields Y" validation to Graph (whose error is more authoritative).

### Changed

- **`tasks_assigned_to_me` return shape is now `{"tasks": [...], "_skipped_profiles": [...]}`** (was a bare list). Single-profile callers see the same data shape with their tasks under `tasks` and an empty `_skipped_profiles`. Each envelope is now stamped with `profile=<active>` (single-profile mode uses the configured profile name; cross-profile mode uses the per-profile name).
- **Planner-half 403 in `tasks_assigned_to_me` no longer raises.** Previously a 403 on `/me/planner/tasks` aborted the whole call; now per-source isolation kicks in — the To Do half is returned and the profile is NOT marked skipped. Common in tenants where the user lacks `Group.Read.All`.

### Engineering

- 432 unit + integration tests + 24 harness tests against real Microsoft Graph (was 328 in v0.3.0). New harness round-trips: recurring Planner task create + read + delete; references add + remove; cross-tenant envelope shape on the harness profile.

## [v0.3.0] — 2026-05-09

UX-gap closures from v0.1/v0.2 plus a non-admin-tenant escape hatch.

### Added

- **Planner deep-links** (`web_url`) for both `planner_*` tools and the cross-source surface. The unified envelope's `web_url` field is no longer always `None` for Planner tasks — it's populated to `https://tasks.office.com/{tenant_id}/Home/Task/{task_id}` where `tenant_id` is extracted from the access token's JWT `tid` claim (no extra `/me` round-trip needed). Closes [#27](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/27). To Do `web_url` remains `None` — there's no documented stable public deep-link pattern for Microsoft To Do; documented inline.
- **`MS_TASKS_NO_PLANNER=true`** env flag for non-admin-tenant users. Microsoft Planner requires `Group.Read.All` (admin-consent in most tenants) — with this flag set, the OAuth scope request drops `Group.Read.All`, the MCP server skips registering all `planner_*` read + write tools, and the cross-source tools (`tasks_assigned_to_me`, `tasks_search`) silently exclude the Planner half. Lets users who only care about Microsoft To Do install without an admin's blessing. Closes [#28](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/28).
- **Helper `tools/_common.tenant_id_from_token`** — JWT-payload `tid` claim extractor (base64url decode + JSON parse, defensive about malformed tokens). Used for deep-link construction; no signature verification (the token came from the trusted token endpoint and we already use it as a bearer credential).
- **RFC `docs/proposals/2026-05-09-graph-search-api-spike.md`** — empirical spike result against Microsoft Graph Search API for `tasks_search`. Outcome: **Withdrawn**. The Graph Search API doesn't support `plannerTask` / `todoTask` entity types (400 BadRequest at the call layer), and the supported types require admin-consent scopes that conflict with `MS_TASKS_NO_PLANNER`. Client-side `tasks_search` stays canonical. Closes [#29](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/29).
- **README v0.2 write-flow dialogue** — second use-case example showing `planner_task_create` x3 + `todo_task_create` + `planner_task_complete`, with the `NOT_OWNED_BY_PROFILE` registry guarantee shown in agent dialogue. Closes [#30](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/30).

### Changed

- **Server registration restructured.** The five Planner read tools moved from `register_read_tools` to a new `register_planner_read_tools`; the four Planner write tools moved to a new `register_planner_write_tools`. `_build_server` calls them conditionally based on `planner_disabled()`. To Do + cross-source registrations stay in `register_read_tools` / `register_write_tools` and are unaffected.
- **`auth/flow.resolve_scopes()` rewritten** to compose scopes from the two independent flags (`TASKS_ALLOW_WRITES`, `MS_TASKS_NO_PLANNER`). Default install behaviour unchanged: `Tasks.Read` + `Group.Read.All` + `User.Read` + `offline_access`.
- **AGENTS.md** project-stack section now lists every env flag.

### Engineering

- 345 unit + integration tests + 23 harness tests against real Microsoft Graph (incl. new test confirming the constructed Planner deep-link is reachable, and 3 To Do + 3 Planner write tests that already exercised the harness sandbox provisioned in v0.2).

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

[Unreleased]: https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/compare/v0.3.0...HEAD
[v0.3.0]: https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/releases/tag/v0.3.0
[v0.2.0]: https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/releases/tag/v0.2.0
[v0.1.0]: https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/releases/tag/v0.1.0
