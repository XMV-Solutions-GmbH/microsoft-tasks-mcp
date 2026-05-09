<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# mcp-server-microsoft-tasks

[![Licence](https://img.shields.io/badge/licence-MIT%20OR%20Apache--2.0-blue.svg)](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/blob/main/LICENSE)
[![CI](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/actions/workflows/ci.yml)
[![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues)

> **In one sentence:** an [MCP](https://modelcontextprotocol.io) server that lets AI coding agents read and **carefully** write your **Microsoft Planner + Microsoft To Do** tasks — never modifying tasks the agent didn't create itself.

## Status — pre-alpha

**Not yet on PyPI.** The repository was bootstrapped on 2026-05-09 from the [`oss-project-template`](https://github.com/XMV-Solutions-GmbH/oss-project-template) v0.3.0; the design is captured in [`docs/app-concept.md`](docs/app-concept.md). No tools are wired up yet — that lands with v0.1.0.

Track progress at <https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues>.

## What is this for?

You work across multiple Microsoft 365 tenants (consultancy, customer engagements, your own org). Tasks are scattered across:

- **Microsoft To Do** — your personal task lists, the place flagged emails land, the place ad-hoc reminders go.
- **Microsoft Planner** — group-scoped boards, one per M365 group / Team, where collaborative work lives.

Surfacing "what do I have to do today" already requires the user to mentally union both. Worse, popular AI agents that *can* talk to Microsoft 365 either:

- bypass Microsoft's modern auth (broken attribution),
- can't see the multi-tenant boundary,
- or auto-modify tasks created by other people (terrifying).

`mcp-server-microsoft-tasks` fixes all three: **local process per tenant, multi-profile, Microsoft Graph for full attribution, read-only by default, writes opt-in, agent-created-only**. The per-profile registry is the hard gate — write tools refuse to touch any task whose ID isn't in the registry of "tasks this profile created".

Sister project to [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp) and [`mcp-server-outlook`](https://github.com/XMV-Solutions-GmbH/outlook-mcp). Same authorship pattern, same auth shape (`mcp-microsoft-graph-auth`), different surface.

## Planned tool surface

### v0.1 (read + login)

| Tool | What it does |
|---|---|
| `tasks_login_begin`, `tasks_login_status` | Non-blocking Device Code login, polled by the agent |
| `todo_lists`, `todo_list_get`, `todo_tasks`, `todo_task_get` | Microsoft To Do — per-user task lists |
| `planner_plans`, `planner_plan_get`, `planner_buckets`, `planner_tasks`, `planner_task_get` | Microsoft Planner — group-scoped plans |
| `tasks_assigned_to_me` | Cross-source: To Do + Planner items currently assigned to the signed-in user |
| `tasks_search` | Cross-source substring search |

### v0.2 (write, opt-in via `TASKS_ALLOW_WRITES=true`)

| Tool | What it does |
|---|---|
| `todo_task_create`, `todo_task_update`, `todo_task_complete`, `todo_task_delete` | Per-profile-registry-gated writes on To Do tasks |
| `planner_task_create`, `planner_task_update`, `planner_task_complete`, `planner_task_delete` | Per-profile-registry-gated writes on Planner tasks |
| `tasks_status` | Inspect this profile's "I created this" registry |

Full surface, auth model, and conflict/safety semantics in [`docs/app-concept.md`](docs/app-concept.md).

## Documentation

| Document | Description |
|---|---|
| [App concept](docs/app-concept.md) | Vision, tool surface, auth model, conflict semantics, Testability |
| [Engineering principles](ENGINEERING_PRINCIPLES.md) | XMV's project-agnostic baseline (test layers, source-control, PR discipline) |
| [AGENTS.md](AGENTS.md) | Brief for AI coding agents — project facts, tech stack, behaviour rules |
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
