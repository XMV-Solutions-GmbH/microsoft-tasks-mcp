<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# mcp-server-microsoft-tasks

[![PyPI version](https://img.shields.io/pypi/v/mcp-server-microsoft-tasks?color=0E7EE0)](https://pypi.org/project/mcp-server-microsoft-tasks/)
[![Licence](https://img.shields.io/badge/licence-MIT%20OR%20Apache--2.0-blue.svg)](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/blob/main/LICENSE)
[![CI](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/actions/workflows/ci.yml)
[![Status: alpha](https://img.shields.io/badge/status-alpha-yellow.svg)](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues)

> **In one sentence:** an [MCP](https://modelcontextprotocol.io) server that lets AI coding agents read your **Microsoft Planner + Microsoft To Do** tasks across all M365 tenants you sign into, without bypassing Microsoft's auth and without ever modifying tasks the agent didn't create itself.

## What is this for?

You work across multiple Microsoft 365 tenants — consultancy, customer engagements, your own org. Tasks are scattered across:

- **Microsoft To Do** — your personal task lists, the place flagged emails land, the place ad-hoc reminders go.
- **Microsoft Planner** — group-scoped boards, one per M365 group / Team, where collaborative work lives.

Surfacing "what do I have to do today" already requires the user to mentally union both surfaces. Worse, popular AI agents that *can* talk to Microsoft 365 either:

- bypass Microsoft's modern auth (broken attribution),
- can't see the multi-tenant boundary,
- or auto-modify tasks created by other people (terrifying).

`mcp-server-microsoft-tasks` fixes all three: **local process per tenant, multi-profile, Microsoft Graph for full attribution, read-only by default, writes opt-in (v0.2+), agent-created-only**. The per-profile registry is the hard gate — write tools refuse to touch any task whose ID isn't in the registry of "tasks this profile created".

Sister project to [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp) and [`mcp-server-outlook`](https://github.com/XMV-Solutions-GmbH/outlook-mcp). Same authorship pattern, same auth shape (`mcp-microsoft-graph-auth`), different surface.

## Installation

```bash
pip install mcp-server-microsoft-tasks
# or, with uv (recommended):
uv tool install mcp-server-microsoft-tasks
# or, on the fly without installing globally:
uvx mcp-server-microsoft-tasks --help
```

Requires Python 3.11+. Works on Linux, macOS, Windows.

## Quickstart

### 1. Sign in once (out of band)

```bash
uvx mcp-server-microsoft-tasks login
```

The output renders the device code first in its own code block, the URL second on its own line. Copy the code, click the link, paste, sign in with your M365 account. Your refresh token is cached locally (OS keyring on macOS / Windows / Linux desktop; encrypted-file fallback otherwise). The MCP server itself never blocks for human interaction afterwards.

### 2. Wire it into Claude Code (or any MCP client)

In your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "microsoft-tasks": {
      "command": "uvx",
      "args": ["mcp-server-microsoft-tasks"]
    }
  }
}
```

Restart Claude Code. The agent now has the full v0.1 read surface (see below). All v0.1 tools are read-only — the consent screen on sign-in shows `Tasks.Read` and `Group.Read.All`, no write scopes.

### 3. Multi-tenant: sign in to a second profile

```bash
uvx mcp-server-microsoft-tasks login --profile customer-acme
```

Then run a second MCP server process pointed at that profile:

```json
{
  "mcpServers": {
    "microsoft-tasks-acme": {
      "command": "uvx",
      "args": ["mcp-server-microsoft-tasks"],
      "env": { "TASKS_PROFILE": "customer-acme" }
    }
  }
}
```

Each profile is one tenant. No cross-tenant token sharing.

## Use case — a daily-shape pulse

Concrete dialogue showing the headline workflow on the v0.1 read surface:

```text
You:    What do I have to do today across To Do and Planner?

Agent:  [calls tasks_assigned_to_me(include_completed=False, limit=20)]

        Five items on your plate, sorted by due date:

        Today
        - "Review draft contract for Acme" (Planner / Sprint 5 / Todo bucket)
          due today, 17:00 — assigned to you + 1 other
        - "Pick up dry cleaning" (To Do / Personal)
          no time set

        Tomorrow
        - "Send follow-up to vendor" (Planner / Customer ops / Doing bucket)
          due tomorrow, 09:00

        Later this week
        - "Renew passport" (To Do / Personal) — Friday
        - "ISO 27001 control review" (Planner / Compliance / Todo)
          Sunday — high priority

You:    What's the deal with the ISO control review? Search my tasks for "27001".

Agent:  [calls tasks_search("27001", source="all")]

        Three matches — one Planner, two To Do:

        - "ISO 27001 control review" (Planner / Compliance, due Sunday)
          → bucket "Todo", priority high, no checklist yet
        - "Read ISO 27001:2022 changes" (To Do / Reading list, no due date)
        - "Schedule auditor call re: ISO 27001 surveillance" (To Do, completed last week)

        Want me to pull the full body and checklist of the Planner one?

You:    Yes please.

Agent:  [calls planner_task_get(task_id="...", include_details=True)]

        "ISO 27001 control review" — full description:

        Quarterly review of all 93 controls in Annex A. Walk through
        the SoA spreadsheet, flag any controls whose ownership has
        changed, attach evidence links from SharePoint.

        Checklist (4 of 12 done):
        - [x] Pull current SoA from SharePoint
        - [x] Identify controls touching authentication
        - [ ] Map to MFA rollout milestone (still open)
        - [ ] ...
```

Every action above is a **read** — no Planner/To-Do state was modified. The server's default install requests no write scopes; the consent screen reads "this app can read your tasks", not "modify". Write tools (create / update / complete / delete) land in v0.2 behind the explicit `TASKS_ALLOW_WRITES=true` env flag.

## v0.1 tool surface (read-only)

| Tool | What it does |
|---|---|
| `tasks_login_begin`, `tasks_login_status` | Non-blocking Device Code login as MCP tools — agent surfaces code + URL without leaving the chat. |
| `todo_lists`, `todo_list_get` | Enumerate / fetch Microsoft To Do lists (default Tasks list, flagged-emails list, user-created lists). |
| `todo_tasks`, `todo_task_get` | List / fetch tasks within a To Do list. `status_filter` narrows to `completed` / `not_completed` / `all`. |
| `planner_plans`, `planner_plan_get` | Enumerate Planner plans across the user's M365 groups (or within one group via `group_id`); fetch one. |
| `planner_buckets` | List buckets (columns) within a Planner plan. |
| `planner_tasks`, `planner_task_get` | List / fetch Planner tasks. `include_details=True` on `_task_get` folds in description, checklist, references. |
| `tasks_assigned_to_me` | Unified across To Do + Planner. Sorted by due date ascending. |
| `tasks_search` | Cross-source substring search; `source="all"` / `"todo"` / `"planner"`. |

Every tool returns a **unified task envelope** with `id`, `title`, `status`, `due_date`, `assignees`, `web_url`, `source`, `etag`, plus source-specific extras (`list_id` / `body_preview` / `categories` / `importance` / `reminder_date` for To Do; `plan_id` / `bucket_id` / `priority` / `percent_complete` / `applied_categories` for Planner). Agents can route follow-up calls correctly off the `source` tag without learning two response shapes.

## v0.2 — write tools, opt-in via `TASKS_ALLOW_WRITES=true`

| Tool | What it does |
|---|---|
| `todo_task_create`, `todo_task_update`, `todo_task_complete`, `todo_task_delete` | Writes on To Do tasks — **only** tasks this profile's registry created. |
| `planner_task_create`, `planner_task_update`, `planner_task_complete`, `planner_task_delete` | Writes on Planner tasks — same registry guarantee. |
| `tasks_status` | Inspect this profile's "I created this" registry. |

To enable, set `TASKS_ALLOW_WRITES=true` in the MCP client config (e.g. via `env` block in `.mcp.json`):

```json
{
  "mcpServers": {
    "microsoft-tasks": {
      "command": "uvx",
      "args": ["mcp-server-microsoft-tasks"],
      "env": { "TASKS_ALLOW_WRITES": "true" }
    }
  }
}
```

The default install does NOT request `Tasks.ReadWrite`. Setting `TASKS_ALLOW_WRITES=true` adds the scope at sign-in time AND registers the write tools at MCP-server-start time.

### The two write-time safety guarantees

1. **Per-profile registry on disk** records every task this server created (`~/.cache/mcp-server-microsoft-tasks/<profile>/tasks.json`, mode 0o600). Write tools refuse — at the tool layer, *before* any Microsoft Graph call — to act on tasks not in the registry. The error is `NOT_OWNED_BY_PROFILE`. Hand-created tasks in Microsoft Planner / To Do are never modified by the agent; tasks created by other agents (different MCP profile, different process, different machine) are likewise untouchable.
2. **ETag-based optimistic concurrency** via `If-Match`. The registry stores the last ETag this server saw; every PATCH / DELETE attaches it; Microsoft Graph returns 412 Precondition Failed if the task changed externally between the agent's read and the write. The MCP surfaces this as `EXTERNALLY_MODIFIED` so the agent re-fetches and decides.

No bulk operations, no auto-assignment to other users, no plan/list creation: each write tool acts on exactly one task per call, and `assignees` on `planner_task_create` is filled only from values the human typed in chat. See [`docs/app-concept.md`](docs/app-concept.md) § Conflict / safety semantics.

## Token storage

`mcp-server-microsoft-tasks` uses `mcp-microsoft-graph-auth` (sister library) to manage tokens. Default backend on macOS / Windows / Linux-desktop is the OS keyring; on headless Linux the fallback is a 0600 plain file at `~/.cache/mcp-server-microsoft-tasks/<profile>/token.json`. For CI / encrypted-file mode, set `MS_TASKS_TOKEN_PASSPHRASE` and `MS_TASKS_TOKEN_STORE=encrypted-file`. Override the auto-pick with `MS_TASKS_TOKEN_STORE=keyring|file|encrypted-file`.

## Documentation

| Document | Description |
|---|---|
| [App concept](docs/app-concept.md) | Vision, tool surface, auth model, conflict semantics, Testability section |
| [Engineering principles](ENGINEERING_PRINCIPLES.md) | XMV's project-agnostic baseline (test layers, source-control, PR discipline) |
| [AGENTS.md](AGENTS.md) | Brief for AI coding agents — project facts, tech stack, behaviour rules |
| [Privacy notice](https://xmv.de/oss/microsoft-tasks-mcp/privacy) | What the OAuth app sees, what XMV sees (nothing), GDPR pointers |
| [Terms of use](https://xmv.de/oss/microsoft-tasks-mcp/terms) | Default OAuth app, BYO override, disclaimer |
| [Contributing](CONTRIBUTING.md) | Contribution flow |
| [Security](SECURITY.md) | Vulnerability disclosure |
| [Changelog](CHANGELOG.md) | Keep-a-changelog history |

## Licence

Dual-licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT License ([LICENSE-MIT](LICENSE-MIT) or <http://opensource.org/licenses/MIT>)

at your option.

### Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in this project by you, as defined in the Apache-2.0 licence, shall be dual-licensed as above, without any additional terms or conditions.

## Contact

- **Organisation**: XMV Solutions GmbH
- **Email**: <oss@xmv.de>
- **Website**: <https://xmv.de/en/oss/>
- **GitHub**: [@XMV-Solutions-GmbH](https://github.com/XMV-Solutions-GmbH)
