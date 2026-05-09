<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Proposal: cross-tenant unified view via `profiles` fan-out

- **Status:** Accepted
- **Authors:** `David Koller <david.koller@xmv.de>`
- **Date drafted:** 2026-05-09
- **Date accepted:** 2026-05-09
- **Tracking issue:** <https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/39>

## Context

The MCP server is single-profile: each process binds to one `TASKS_PROFILE` (one tenant, one signed-in user) at start-up. People who consult to multiple organisations (the "consultant in three tenants" mode that `docs/app-concept.md` § Future scope flags) sign in once per profile, run separate MCP-server processes, and rely on the agent to ask each in turn.

This works but it pushes integration complexity onto the agent and onto the user (they have to teach the agent which profiles exist, in what order to ask, how to merge). Asking *"what do I have to do across all my orgs?"* should be one tool call.

The cross-source surface (`tasks_assigned_to_me`, `tasks_search`) already merges To Do + Planner within one tenant. Extending it to merge **across** tenants is a natural next step — and the per-profile token cache + per-profile registry pattern already gives us the credentials we need.

## Decision

Add an optional `profiles: list[str] | None = None` parameter to the cross-source tools. When `None` (default), behaviour is unchanged — single profile. When a list, each profile's results are fetched independently and merged into one envelope-list, with each entry tagged with its source `profile`.

Concretely, in this PR:

- `tasks_assigned_to_me` accepts `profiles=["acme", "globex"]`.
- For each profile, the function calls `get_token(profile)`, makes the per-source Graph calls (Planner + To Do), and tags every returned envelope with `"profile": "<name>"`.
- A profile whose token has expired or whose Graph call fails (403 / 401) is **skipped with a logged warning**, not aborted. The agent gets the partial result with a clear `_skipped_profiles` field listing what didn't load.
- Sequential execution. Parallelisation is deferred (Q3 below) — we expect 2-4 profiles in practice and the latency budget is fine for that.
- `tasks_search` is **not** updated in this PR. It's a larger surface (To Do enumeration is paginated and search is client-side) and its fan-out has the same shape, so we factor it into a follow-up issue once the `tasks_assigned_to_me` shape is field-validated.

## Alternatives considered

### Alternative A: external aggregator agent

The agent runs N MCP server processes, one per profile (the user already does this today), and merges results client-side.

Rejected because: it makes "give me everything across orgs" a multi-turn agent task with brittle merging logic, and the agent has to learn the shape on each install. The merging belongs in the server where we control the invariant.

### Alternative B: a separate `aggregate_*` tool surface

A new tool `aggregate_tasks_assigned_to_me(profiles=[...])` that wraps the per-profile call. Keeps the per-profile tools simple.

Rejected because: it doubles the tool surface for what is fundamentally one-flag behaviour. Agents discover tools by name; making them learn `tasks_assigned_to_me` AND `aggregate_tasks_assigned_to_me` for the same intent adds friction without new capability.

### Alternative C: implicit "all configured profiles"

Read `MS_TASKS_PROFILES` env var as a comma-separated list and always merge.

Rejected because: it forces a single behaviour on the install. Some agents want one-tenant view by default ("what's on my plate at work today") and only occasionally want cross-tenant ("monthly reconciliation"). The explicit `profiles` parameter on the tool keeps both modes available.

## Consequences

- The unified envelope gains a `profile` key (str | None). Callers that don't pass `profiles` continue to see `profile=None`-stamped entries (or — to keep diffs minimal — the default-single-profile path may omit the key entirely; the simpler choice is to ALWAYS stamp with `profile=<active>` even in the single-profile case, which is what we're going with).
- Per-profile failure must not abort the whole call. The contract: best-effort merge, with `_skipped_profiles` listing the names that didn't load and why (token expired, 403, 5xx, etc.).
- Sort order is preserved — merge first, then sort by `due_date ascending (None last)` exactly as before.

## Open questions / future work

- **Q1 — Parallel fan-out.** Sequential is fine for 2-4 profiles, but a consultant in 8+ profiles will feel it. Adding `httpx.AsyncClient` + `asyncio.gather` is mechanical once we agree the failure-isolation model. Track in a follow-up.
- **Q2 — Profile discovery.** The agent has to know which profile names exist (currently from the MCP-config `env` block). A new `tasks_status_all_profiles()` tool that lists the cached profiles + their token state would let the agent self-discover. Track separately.
- **Q3 — Cross-profile dedupe.** Some Planner plans are visible across multiple tenants via guest-account membership. The same `task.id` can in theory appear in two profiles' results. Today we don't dedupe — we present both, since each result is in a different "profile" context. Document this limitation; revisit if it surfaces in real use.
- **Q4 — `tasks_search` extension.** Same fan-out shape, deferred to a follow-up issue once the `assigned_to_me` shape is validated against real consultant usage.
