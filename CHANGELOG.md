<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Tracked in [GitHub Issues](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues).

### Added

- Repository bootstrapped from the [`oss-project-template`](https://github.com/XMV-Solutions-GmbH/oss-project-template) v0.3.0.
- [`docs/app-concept.md`](docs/app-concept.md) — vision, MVP tool surface (v0.1 read tools + v0.2 write tools), auth model (delegated Device Code; `Tasks.Read` always, `Tasks.ReadWrite` only with `TASKS_ALLOW_WRITES=true`, `Group.Read.All`, `User.Read`, `offline_access`), conflict / safety semantics (per-profile registry, ETag-based optimistic concurrency, never-modify-other-people's-tasks), Testability section per `ENGINEERING_PRINCIPLES.md` § 5.
- Python project skeleton: `pyproject.toml` (mcp ≥ 1.2 + mcp-microsoft-graph-auth ≥ 0.1.1 + httpx + keyring + cryptography; ruff + mypy strict + pytest + respx), `src/microsoft_tasks_mcp/` package layout, `tests/{unit,integration,harness}/` three-layer structure, `tests/run_tests.sh` dispatcher.
- CI workflow adapted for Python (uv + ruff + ruff-format + mypy + pytest with codecov upload), three-job shape lint / test / harness; harness job restores `MS_TASKS_HARNESS_TOKEN_JSON` from a repo secret and skips silently when absent.
- Release workflow with PyPI Trusted Publisher (OIDC) — gates on the test suite, builds wheel + sdist via `uv build`, publishes via `uv publish` to `mcp-server-microsoft-tasks`, then creates a GitHub Release.
- AGENTS.md filled in with project facts, tech stack, project-specific overrides (PR-from-first-release-day-one, harness sandbox notes, harness-token-renewal chore, **non-blocking `tasks_login_begin` is mandatory** per the outlook v0.3.0 incident).
