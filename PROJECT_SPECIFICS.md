<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# PROJECT_SPECIFICS.md — `mcp-server-microsoft-tasks`

Project-specific content for `mcp-server-microsoft-tasks`. Read after `AGENTS.md` per its reading order. Everything in here is specific to this repo; the generic agent rules live in `AGENTS.md` + `ENGINEERING_PRINCIPLES.md` + `PROJECT_MANAGEMENT_PRINCIPLES.md`.

## What this project is

`mcp-server-microsoft-tasks` — an MCP server that wraps Microsoft Planner + Microsoft To Do (the Microsoft Tasks family) so AI coding agents can read, search, and **carefully** create tasks across both surfaces, **without ever modifying tasks the agent did not create itself**.

Full vision, tool surface, auth model, and conflict semantics in [`docs/app-concept.md`](docs/app-concept.md). Read it before changing anything that touches the public surface — especially anything tied to the per-profile registry or the `TASKS_ALLOW_WRITES` opt-in.

## Project-specific docs

| Doc | Purpose |
|---|---|
| [`docs/app-concept.md`](docs/app-concept.md) | Vision, MVP scope, public surface, Testability section, open questions |
| [`docs/testconcept.md`](docs/testconcept.md) | Per-project instantiation of the three test layers (unit / integration / harness) |
| [`docs/proposals/`](docs/proposals/) | RFCs / spike notes / architectural decisions too big for a single issue |
| [`docs/markdown-style.md`](docs/markdown-style.md) | Markdown linting rules — read only when producing or editing Markdown |
| [`README.md`](README.md) | Quickstart for end users |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution flow |
| [`SECURITY.md`](SECURITY.md) | Vulnerability disclosure |
| [`CHANGELOG.md`](CHANGELOG.md) | Keep-a-changelog history |

## Tracker

**GitHub Issues + the repo-bound GitHub Project** at <https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues>. See `ENGINEERING_PRINCIPLES.md` § 2. No `docs/todo.md` or other markdown TODO files.

Recommended labels: `type:feat` / `type:fix` / `type:chore` / `type:docs` / `type:test`; `area:<component>`; `priority:p0` / `p1` / `p2`. Add `agent:<tool-name>` (e.g. `agent:claude`, `agent:codex`) when an AI agent is the executor.

Issue body convention: `## Context`, `## Acceptance criteria` (checkbox list), `## Out of scope`, `## Links`. Milestones map to releases (`v0.1.0 — MVP`, `v0.2.0`, …).

## Tech stack

- **Python 3.11+**, packaged for `uvx` / `pipx` install.
- **MCP Python SDK** (`mcp[cli]`) with FastMCP for the protocol layer.
- **`mcp-microsoft-graph-auth`** (sister library on PyPI) for the Device Code flow, token store, login session registry, public-view shape. Same auth primitives as `mcp-server-sharepoint` and `mcp-server-outlook`.
- **`httpx`** for raw Microsoft Graph calls.
- **Tests**: `pytest` + `pytest-asyncio` + `respx` for HTTP boundary mocks; harness layer hits the real Microsoft Graph against a dedicated M365 sandbox.
- **Lint/format**: `ruff` (replacing flake8 + black + isort), `mypy` strict.
- **Build**: `uv` for lock + sync + build. Hatchling backend.
- **Auth scopes (delegated)**: `Tasks.Read` (always), `Tasks.ReadWrite` (only when `TASKS_ALLOW_WRITES=true`), `Group.Read.All` (Planner — admin-consent; dropped when `MS_TASKS_NO_PLANNER=true`), `User.Read`, `offline_access`.
- **Env flags**: `TASKS_ALLOW_WRITES=true` (registers write tools + adds `Tasks.ReadWrite` scope); `MS_TASKS_NO_PLANNER=true` (skips Planner tool registration + drops `Group.Read.All` scope, for non-admin tenants); `TASKS_PROFILE=<name>` (per-tenant cache namespace; default `default`); `TASKS_CLIENT_ID` / `TASKS_TENANT_ID` (BYO Entra app override); `MS_TASKS_TOKEN_STORE=keyring|file|encrypted-file` (override token-store auto-pick); `MS_TASKS_TOKEN_PASSPHRASE` (required for encrypted-file backend).

## Project-specific overrides of the engineering baseline

- **PR workflow already triggered (per § 13).** From the moment `mcp-server-microsoft-tasks` is on PyPI, treat `main` as deployable trunk: feature branches + PRs, branch protection on `main`, CI green required for merge. Until the first published release, direct commits to `main` are acceptable for chores and docs (and have been used during the bootstrap).
- **Test environment (per § 5).** A dedicated M365 group + Planner plan + To Do test list in the XMV tenant — see `docs/app-concept.md` § Testability. Credentials live in GitHub Actions secrets for CI (`MS_TASKS_HARNESS_TOKEN_JSON`) and in a developer-local profile (`harness`) for iterative work.
- **Harness token renewal.** Monthly recurring chore: Microsoft refresh tokens rotate every ~60–90 days, so the `MS_TASKS_HARNESS_TOKEN_JSON` repo secret has to be refreshed before CI's harness job starts failing. Same shape as `sharepoint-mcp`'s `scripts/renew-harness-token.sh`.
- **Non-blocking login from day one (per § 5 and the outlook v0.3.0 incident).** `tasks_login_begin` MUST return immediately with `status="pending"` plus `user_code` + `verification_url`; never block on the polling task. The agent polls `tasks_login_status` for state changes. Blocking deadlocks the UX on clients that don't render progress notifications.

## License header for new source files

This project is dual-licensed **MIT OR Apache-2.0**, copyright **XMV Solutions GmbH**. Generic SPDX rules in `ENGINEERING_PRINCIPLES.md` § 11; concrete examples for this project below.

For Python, Shell, YAML, TOML, and most languages with `#` line comments:

```text
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: <year> XMV Solutions GmbH
# SPDX-FileContributor: <git user.name> <<git user.email>>
```

For languages with `//` line comments (Go, Rust, JS/TS, Java, …):

```text
// SPDX-License-Identifier: MIT OR Apache-2.0
// SPDX-FileCopyrightText: <year> XMV Solutions GmbH
// SPDX-FileContributor: <git user.name> <<git user.email>>
```

For HTML / Markdown:

```html
<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: <year> XMV Solutions GmbH
SPDX-FileContributor: <name> <<email>>
-->
```

The first `SPDX-FileContributor` line is set when the file is created and is **never overwritten** — this honours the German *Urheberrecht*. New substantial contributors append additional lines. The agent populates the line from the current `git config user.name` / `user.email`.

## Documentation scaling threshold

If `docs/app-concept.md` plus the relevant supporting docs exceed roughly **50k tokens (~200 KB combined)**, split into a two-level structure:

1. Keep `docs/app-concept.md` as an index — vision, summary, table of contents with links.
2. Move thematic deep-dives into `docs/app-concept/*.md` chapters (e.g. `architecture.md`, `security.md`, `api-design.md`).

Rationale: AI agents should use ≤1/3 of their context window for project instructions, leaving room for code and conversation.

## Environments + URLs

- **Tracker / Project board**: <https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues>
- **Distribution**: PyPI (`mcp-server-microsoft-tasks`), installed via `uvx` / `pipx`.
- **Harness sandbox**: a dedicated M365 group + Planner plan + To Do test list in the XMV tenant — see `docs/app-concept.md` § Testability.
- **CI harness secret**: `MS_TASKS_HARNESS_TOKEN_JSON` (GitHub Actions), refreshed monthly; developer-local equivalent is the `harness` profile.

## Glossary

- **Microsoft Tasks family** — the umbrella for Microsoft Planner + Microsoft To Do, the two task surfaces this server wraps.
- **Public-view shape** — the redacted task representation returned to agents; same primitive as the sister `mcp-server-*` auth libraries.
- **Profile** — a per-tenant cache namespace selected by `TASKS_PROFILE` (default `default`); the `harness` profile targets the test sandbox.
- **Harness layer** — the third test layer that hits the real Microsoft Graph against the M365 sandbox (see `ENGINEERING_PRINCIPLES.md` § 5 and `docs/testconcept.md`).
