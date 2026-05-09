<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# mcp-server-microsoft-tasks — App Concept

A Model Context Protocol server that lets AI coding agents read and **carefully** write Microsoft Tasks — i.e. **Microsoft Planner** (group-scoped) and **Microsoft To Do** (per-user lists), unified — **without ever modifying tasks the agent did not create itself**.

Sister project to [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp) and [`mcp-server-outlook`](https://github.com/XMV-Solutions-GmbH/outlook-mcp). Same authorship pattern, same OSS template, same auth shape (`mcp-microsoft-graph-auth` shared lib) — different surface.

---

## Why this exists

For operators in multi-tenant consultancy / customer-engagement contexts (the "I'm in three different companies' Microsoft tenants this quarter" reality), an agent that can *see* and *carefully add to* the user's Microsoft Tasks is high-leverage:

- **A consultant's "follow-up after the meeting" workflow** — after a call, the agent transcribes outcomes and drafts a few Planner tasks in the right plan + bucket, with the right assignees, the right due dates. The user reviews; the user accepts.
- **A daily-shape pulse** — the agent reads `tasks_assigned_to_me`, surfaces what's overdue, what's due today, what's blocked, and what conversation context (mail thread, SharePoint doc) each task relates to.
- **Cross-source unification** — "what do I have to do today" should not require the user to mentally union three different Microsoft surfaces (To Do default list, To Do flagged-mails list, Planner across all M365 groups). The MCP returns a single list.

The bad alternatives without this MCP:

- **Manual triage** of each surface separately — slow, error-prone, no AI assistance.
- **Auto-modifying agents** — terrifying. One wrong tool call and a colleague's Planner task says it's done when it's not. Audit trail says it was *you* who marked it done.
- **Custom IFTTT-style sync engines** — bypass Microsoft's modern auth, lose attribution, can't see the multi-tenant boundary.

This MCP fixes all three: **local process per tenant, multi-profile**, **Microsoft Graph for full attribution**, **read-only by default, writes opt-in, agent-created-only**.

---

## Core use cases

1. **Read-only triage** — agent surfaces what's assigned to the user, across both To Do and Planner, with deadlines, owners, and source tags. No mutations.
2. **Cross-source search** — "find me anything related to ISO 27001 in my tasks" returns hits from both To Do lists and Planner plans.
3. **Drafting follow-up tasks** (write, opt-in) — after a meeting summary, the agent calls `planner_task_create` to add 3–5 tasks to the right plan + bucket. The user sees them in Planner / Microsoft Teams Planner tab.
4. **Closing tasks the agent itself created** (write, opt-in) — the agent can mark *its own* tasks complete or delete them, but never touches tasks created by a human or another agent. Per-profile registry enforces this.

---

## Non-goals

- **Never auto-modify other people's tasks.** The per-profile registry is the hard gate: write tools refuse to touch any task that isn't in this profile's "I created this" registry. ETag mismatches from external edits return a clear error rather than overwriting.
- **No bulk destructive operations.** No `delete_all_completed`, no `update_many`. Each write tool acts on exactly one task per call.
- **Not a plan-management tool.** No `planner_plan_create`, no `planner_plan_delete`, no bucket management. Plans are admin-territory; v0.x stays out.
- **No auto-assignment of tasks to other users.** The agent proposes assignees in chat; the user enters them in the create-task call explicitly. There is no scenario where the agent silently puts work on someone else's plate.
- **Not a sync engine.** No local mirror, no offline cache. Each call hits Microsoft Graph live.
- **Not a Teams / Outlook / SharePoint MCP.** Sibling MCPs cover those surfaces.

---

## Tool surface

### v0.1 — read tools (always available)

```text
# Microsoft To Do — per-user task lists
todo_lists(limit=50)
todo_list_get(list_id)
todo_tasks(list_id, status_filter?, limit=100)
todo_task_get(task_id)

# Microsoft Planner — group-scoped, M365-Group-backed plans
planner_plans(group_id?, limit=50)
planner_plan_get(plan_id)
planner_buckets(plan_id)
planner_tasks(plan_id, bucket_id?, status_filter?, limit=100)
planner_task_get(task_id, include_details=False)

# Cross-source convenience
tasks_assigned_to_me(include_completed=False, limit=100)
tasks_search(query, source="all"|"todo"|"planner", limit=50)
```

Each tool returns a structured payload with at least: `id`, `title`, `status`, `due_date`, `assignees`, `web_url`, `source` (`"todo"` / `"planner"`), plus source-specific fields (To Do: `list_id`, `body_preview`, `categories`, `importance`, `reminder_date`; Planner: `plan_id`, `bucket_id`, `priority`, `percent_complete`, `checklist`, `references`).

### v0.1 — login tools (always available)

```text
tasks_login_begin(profile?, force=False)
tasks_login_status(profile?)
```

**Non-blocking** by design from day one — `tasks_login_begin` returns immediately with `status="pending"` plus `user_code` and `verification_url`; the agent polls `tasks_login_status` until it flips to `signed_in`. This avoids the deadlock that bit `mcp-server-outlook` v0.3.0 (where the blocking poll meant agents on clients without progress notifications saw a blank response until the device code expired).

`force=True` on `tasks_login_begin` cancels any in-flight pending session and starts fresh, replacing what would otherwise be a separate `cancel` tool.

### v0.2 — write tools (opt-in via `TASKS_ALLOW_WRITES=true`)

```text
todo_task_create(list_id, title, body?, due_date?, importance?)
todo_task_update(task_id, title?, body?, due_date?, status?)   # only profile-created
todo_task_complete(task_id)                                    # only profile-created
todo_task_delete(task_id)                                      # only profile-created

planner_task_create(plan_id, bucket_id, title, body?, due_date?, assignees?)
planner_task_update(task_id, ...)                              # only profile-created
planner_task_complete(task_id)                                 # only profile-created
planner_task_delete(task_id)                                   # only profile-created

tasks_status()
    → list tasks this profile has created, with their current Graph state
```

`tasks_status()` is the agent's own registry-inspection tool: it returns the per-profile list of tasks the agent itself created (still-live ones plus their last-known status), so the agent can decide whether to follow up on its own work.

### Explicitly NOT exposed

- Bulk update/delete across the user's tasks.
- Modifying tasks the agent did not create — the per-profile registry enforces this; an `etag` mismatch from external edits returns a clear `EXTERNALLY_MODIFIED` error rather than overwriting.
- Plan creation, plan deletion, bucket management — admin territory; out of scope.
- Auto-assignment of tasks to other users beyond what the user explicitly typed in the call.

---

## Auth model

OAuth 2.0 **Device Code flow** against Microsoft Identity v2.0, **delegated** scopes (acting as the signed-in user, not as a service principal). The audit trail says the user did it; the agent ran the toolchain.

### Required delegated scopes

| Scope | When | Why |
|---|---|---|
| `Tasks.Read` | v0.1 always | Read both To Do and Planner tasks |
| `Tasks.ReadWrite` | v0.2 only, when `TASKS_ALLOW_WRITES=true` | Create/update/delete tasks |
| `Group.Read.All` | always | Enumerate the M365 groups whose Planner plans the user has access to (Planner is group-scoped; without this, `planner_plans()` can't list anything) |
| `User.Read` | always | `/me` lookup for the signed-in UPN, used by `tasks_login_status` and registry attribution |
| `offline_access` | always | Refresh tokens (typical 60–90 day lifetime) so the user signs in once, not every session |

`Group.Read.All` is admin-consent-required in most tenants. The Entra app registration has it pre-granted with tenant-wide admin consent in the XMV tenant; for external installs, the tenant admin grants it once on first install via the standard consent prompt.

### Token storage + multi-profile

Same shape as the sister projects via `mcp-microsoft-graph-auth`:

- Token cache on the user's machine, OS keyring preferred (`keyring` library), encrypted-file fallback for headless environments.
- Multi-profile via `TASKS_PROFILE` environment variable (default: `default`). Each profile is one signed-in identity; running two MCP server processes with different `TASKS_PROFILE` values lets a consultant work in two M365 tenants in parallel.
- `tasks_login_begin` / `tasks_login_status` drive the Device Code flow without leaving the agent dialogue.

---

## Conflict / safety semantics

### Per-profile "I created this" registry

The MCP server keeps a persistent per-profile registry of tasks it created via the agent. Same shape as `mcp-server-outlook`'s draft registry: JSON file on disk, one entry per task, persisted across server restarts.

Registry entry: `{task_id, source ("todo"|"planner"), list_or_plan_id, created_at, last_known_etag}`.

Write tools (`todo_task_update` / `_complete` / `_delete`, same for Planner) **refuse** to act on a task whose `task_id` is not in the registry. The agent gets an explicit error (`NOT_OWNED_BY_PROFILE`) rather than a silent successful write to someone else's task.

### ETag-based optimistic concurrency

Every read returns the task's `@odata.etag` (To Do) or HTTP `ETag` header (Planner). Write tools attach the last-known ETag via `If-Match`. If the underlying task was modified externally between the read and the write, the Graph API returns 412 Precondition Failed; the MCP surfaces this as `EXTERNALLY_MODIFIED`.

This catches the case where the user themselves edited the task in the Microsoft client between the agent's read and the agent's write — the user's edit isn't silently clobbered.

### Read-only by default

The default install registers only the read tools + login tools. Write tools are registered only when `TASKS_ALLOW_WRITES=true`. The OAuth scope set is also conditional: `Tasks.ReadWrite` is requested only when the env flag is set, so a default install's consent prompt stays read-only.

### No autonomous decisions on assignees

`planner_task_create(plan_id, bucket_id, title, ..., assignees?)` accepts an `assignees` argument with explicit user-IDs. The agent only fills it from values the user typed in chat. There's no codepath where the agent looks up colleagues and assigns them work without explicit human typing.

---

## Tech stack

- **Python 3.11+**, packaged for `uvx` / `pipx` install. Same shape as sister projects.
- **MCP Python SDK** (`mcp[cli]>=1.x`) with FastMCP for the protocol layer.
- **`mcp-microsoft-graph-auth`** (sister library on PyPI) for Device Code flow, token store, login session registry, public-view shape. Same auth primitives as `mcp-server-sharepoint` and `mcp-server-outlook`.
- **`httpx`** for raw Microsoft Graph calls. Reasoning per the SharePoint tech-spike: SDK gives little value for the surface area we use; raw `httpx` keeps the dependency tree small and the test mocks (via `respx`) trivial.
- **Tests**: `pytest` + `pytest-asyncio` + `respx` for HTTP mocks. Three layers per `ENGINEERING_PRINCIPLES.md` § 5 — see Testability below.
- **Lint/format**: `ruff` (replacing flake8 + black + isort), `mypy` strict.
- **Build**: `uv` for lock + sync + build. Hatchling backend.

---

## Testability

Per [`ENGINEERING_PRINCIPLES.md` § 5](../ENGINEERING_PRINCIPLES.md), every project names all three test layers explicitly. This is the operationalisation for `mcp-server-microsoft-tasks`:

| Layer | Where | What it verifies | External world | Speed |
|---|---|---|---|---|
| **Unit** | `tests/unit/` | Pure-function logic in isolation. Tool implementations are tested with `respx` mocking `graph.microsoft.com`, an in-memory `TokenStore`, an in-memory `LoginSessionRegistry`. | All externals mocked | sub-second per test |
| **Integration** | `tests/integration/` | Cross-module wiring with boundary mocks. Tool registration in the MCP server, auth shim integration with the shared lib, registry persistence across restarts. | Boundary mocks (`respx` against Graph; `tmp_path` for the on-disk registry) | <1 s per test |
| **Harness** | `tests/harness/` | Our code against the **real Microsoft Graph + a real M365 sandbox**. Real Device Code login (cached refresh token), real Planner plan in a real M365 Group, real To Do default list. | Real network, real Graph endpoints, real least-privilege user | seconds per test (network bound) |

**Harness is the gate.** No v0.1 feature ticket lands without a corresponding harness test, or a documented justification for why one isn't possible (e.g. a destructive test where the cleanup story isn't tractable yet).

### Harness sandbox

- **M365 tenant**: XMV Solutions tenant.
- **Test user**: `d.koller@xmv.de` — same user as the sister projects' harness, smallest-license-that-includes-Tasks (E5 Developer in this case).
- **M365 Group**: a dedicated group `microsoft-tasks-mcp-harness@xmv.de` (TBD on first bootstrap), with a single Planner plan named `Harness` containing two buckets `Todo` and `Done`. The test user is a member of the group.
- **To Do test list**: per-user, named `harness` (or the default list if no other choice).
- **Why a real user, not a service principal**: v0.1 only supports delegated user auth (no client-credentials flow). A leaked harness refresh token lets an attacker act as `d.koller@xmv.de` against this user's tasks only — bounded by the user's permissions.
- **Cleanup discipline**: harness tests that mutate state clean up after themselves via teardown fixtures. A stale `harness` plan filling up with orphan tasks is a defect; the test that creates them is responsible for deleting them.

### What runs where

- `./tests/run_tests.sh` (default = unit + integration) — runs in CI on every PR. No M365 credentials needed.
- `./tests/run_tests.sh harness` — requires `harness` profile token cache (run `uv run mcp-server-microsoft-tasks login --profile harness` once locally, or restore from `MS_TASKS_HARNESS_TOKEN_JSON` in CI).
- `./tests/run_tests.sh all` — unit + integration + harness in one shot.

The `tests/conftest.py` auto-marks tests by their parent directory, so `pytest -m unit` / `-m integration` / `-m harness` filter correctly without each test having to apply the marker by hand.

---

## Open tech-spike questions

These get resolved before they block feature work; resolutions land in `docs/proposals/` per the engineering principles.

### Q1 — Cross-source search semantics

To Do has **no native search endpoint** on `/me/todo/lists/{id}/tasks`. Planner has nothing more either. Two options for `tasks_search`:

- **A)** Client-side: enumerate all lists / plans the user has access to, fetch all tasks, filter by `query` substring locally. Slow at scale, but correct.
- **B)** Microsoft Graph Search API (`/search/query`): supports task entities for some flavours. Worth a spike to confirm coverage and rate-limit behaviour.

Decision: **start with A** (client-side, with `limit=50` cap). Spike B in v0.2+ if A is too slow in practice.

### Q2 — `tasks_assigned_to_me` unification

- Planner has `/me/planner/tasks` (clean — returns all Planner tasks assigned to current user).
- To Do has **no equivalent global endpoint**. Have to enumerate the user's lists, then their tasks, filter `status != completed` (or include if `include_completed=True`).

Decision: in v0.1, two separate calls (one per surface), then merge client-side. Cap per source at `limit/2` initially.

### Q3 — ETag handling differences

- To Do: ETag in `@odata.etag` field of the JSON payload.
- Planner: ETag in `@odata.etag` JSON field for some endpoints, `ETag` HTTP header for others.

Decision: the auth/transport shim hides the difference; tool implementations get a uniform `etag` string back from a central helper.

### Q4 — Registry persistence shape

Same JSON-on-disk shape as `mcp-server-outlook`'s draft registry, scoped per profile. `~/.cache/mcp-server-microsoft-tasks/<profile>/registry.json`. Backwards-compat additive only; new fields default-tolerant.

### Q5 — `Group.Read.All` consent friction

`Group.Read.All` is admin-consent-required in most tenants. For the public install path (someone outside the XMV tenant runs `uvx mcp-server-microsoft-tasks login`), the consent prompt requires a tenant admin to approve. Document this in README; consider a future `MS_TASKS_NO_PLANNER=true` env flag that drops `Group.Read.All` from the scope set and disables Planner tools at runtime, so non-admin tenants can still use the To Do half.

---

## Future scope (v0.3+, not in MVP)

- **Subscribed plans** — agent watches a Planner plan for changes (Microsoft Graph change notifications via webhook). Useful for "ping me when this task is reassigned to me".
- **OneNote-linked task references** — Planner tasks can have `references` (URLs); link out to OneNote pages. Read-side surfacing in v0.3+.
- **Cross-tenant unified view** — currently each `TASKS_PROFILE` is one tenant; running two profiles gives two independent views. A cross-profile aggregate would be one MCP call returning tasks across both — useful for the "consultant in three tenants" mode but adds complexity (which token gets used for which call?). Defer.
- **`MS_TASKS_NO_PLANNER`** — see Q5 above; opt-out for non-admin tenants.
