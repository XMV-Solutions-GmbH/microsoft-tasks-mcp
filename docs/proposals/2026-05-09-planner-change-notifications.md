<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Proposal: Planner change notifications — webhook vs. polling

- **Status:** Accepted (poll-only); webhook deferred to v0.5
- **Authors:** `David Koller <david.koller@xmv.de>`
- **Date drafted:** 2026-05-09
- **Date accepted:** 2026-05-09
- **Tracking issue:** <https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/41>

## Context

`docs/app-concept.md` § Future scope lists *"Subscribed plans — agent watches a Planner plan for changes (Microsoft Graph change notifications via webhook)"* as a v0.3+ candidate. The use case: an agent can answer *"ping me when this task is reassigned to me"* without re-polling every minute.

Microsoft Graph supports two change-notification modes for `plannerTask` and `plannerPlan`:

1. **Webhook (HTTP push)** — Graph POSTs to a tenant-supplied `notificationUrl` whenever a subscribed resource changes. Requires the URL to be publicly reachable over HTTPS, with a valid TLS cert chain.
2. **WebSocket / Azure Event Hub** — newer and limited to a subset of resources; not yet GA for Planner at the time of writing.

The MCP server, by design, runs *locally* (installed via `uvx` on the user's laptop, served over stdio to the MCP client). It has no public HTTPS endpoint and no static IP. That fundamental shape clashes with the webhook model.

## Decision

**Ship a polling-based "change since last poll" tool in v0.4** (`tasks_changes_since`). Defer real webhook subscriptions to v0.5, gated on solving the public-endpoint problem.

The polling tool re-fetches a configurable scope (a specific plan, a list of plan ids, or "all my Planner-assigned tasks") on each call, diffs against an on-disk cursor (last-seen `lastModifiedDateTime` per task), and returns the delta. Cursor is per-profile, persisted next to the task registry. First call returns "everything is new" (fresh cursor), subsequent calls return only changes.

This is genuine "what changed since I last checked", just synchronous-on-demand instead of push-driven. Most agent flows ("on each turn, what's new?") fit a pull model fine. The cost: agents miss real-time push semantics, but they don't need them — they're not running 24/7.

## Alternatives considered

### Alternative A: real webhook subscriptions, requiring user to run a tunnel

Have `tasks_subscribe` create a Microsoft Graph subscription pointing at a user-supplied `notificationUrl` (typically an `ngrok` / `cloudflared` tunnel that proxies to a local HTTP server the MCP runs on a high port).

Rejected because:

- It pushes operational complexity onto every install: users have to provision a tunnel, keep it running, and re-create the Graph subscription every 3 days when Graph's max-lifetime expires.
- It introduces a new attack surface (the local HTTP server accepting unauthenticated POSTs from "Microsoft Graph", verifiable only via a `clientState` shared secret).
- Failure modes are silent: the tunnel goes down → notifications stop → the agent thinks "all quiet" when in fact it's deaf.
- The class of users who *can* run a tunnel is small and overlaps poorly with the class of users who use a tasks-MCP.

If we ship this later, it should be opt-in via a separate companion package (`mcp-server-microsoft-tasks-webhook`), not the default install.

### Alternative B: depend on a hosted relay service

Run a tiny hosted webhook receiver (e.g. on Vercel / Cloudflare Workers) that the MCP polls for queued events. Microsoft Graph posts to the relay; the local MCP polls the relay; the relay returns events.

Rejected because:

- It adds a runtime dependency on an XMV-operated service, which isn't compatible with "single-tenant, no telemetry, runs on your laptop". Also costs money and uptime.
- Now we have *two* sources of truth that can drift (the relay's queue and Graph's actual current state).

### Alternative C: poll-based change tool (chosen)

Synchronous "give me changes since cursor" tool. Implementation:

- `tasks_changes_since(scope=…, max_results=200)` — scope is one of:
  - `{"kind": "plan", "plan_id": "..."}` — polls `/planner/plans/{id}/tasks`.
  - `{"kind": "assigned_to_me"}` — polls `/me/planner/tasks`.
  - `{"kind": "registry"}` — polls every task in this profile's registry, one GET per id (chunked).
- On-disk cursor: `~/.cache/mcp-server-microsoft-tasks/<profile>/cursors.json`, keyed by scope-hash. Stores `{last_modified_max, seen_ids}`.
- Diff: any task with `lastModifiedDateTime > cursor.last_modified_max` OR with an id NOT in `seen_ids` is "new/changed". Tasks present in `seen_ids` but absent from the response are "deleted/no-longer-visible".
- Returns: `{"added": [envelopes], "modified": [envelopes], "removed": [{id, last_known_title}]}` plus an updated cursor that the caller can ignore (server-side persistence).

### Alternative D: do nothing, defer entirely to v0.5

Just leave the issue open and revisit when there's a clear public-endpoint story.

Rejected because: the agent's "what changed?" intent is real and currently unaddressed. Polling buys most of the value for a fraction of the complexity, and shipping it sets up the eventual webhook flavour as a strict performance optimisation rather than a green-field feature.

## Consequences

- New tool surface (`tasks_changes_since`) + new on-disk file (`cursors.json`, mode 0o600, sibling of `tasks.json`).
- The cursor's `last_modified_max` is monotonic — if Graph ever returns a `lastModifiedDateTime` *earlier* than what we've seen, we ignore it (Graph's clock isn't ours; trust the latest).
- Polling latency depends on call cadence. The MCP doesn't drive this — the agent does. Document expected use: "call this every turn that mentions tasks, or every N minutes if doing background watch".
- Webhook subscription tools (`tasks_subscribe` / `tasks_unsubscribe`) are explicitly **not** in v0.4. They're tracked as a v0.5+ initiative gated on a working public-endpoint story (companion package or Microsoft hosting Graph→WebSocket bridges for Planner — both unresolved upstream).

## Open questions / future work

- **Q1 — What about Planner plans the user is no longer a member of?** A poll on `/me/planner/tasks` will silently omit them; the diff would mark every previously-seen task in that plan as "removed". We may want a heuristic that detects "this is membership loss, not task deletion" by also polling `/me/memberOf` and excluding plans the user just dropped. Defer — log + flag as `{reason: "plan_no_longer_visible"}` in the response so the agent can hint at this.
- **Q2 — To Do change notifications.** Same shape — poll `/me/todo/lists/{id}/tasks` per list. The cursor-key shape is symmetric; the implementation can share. Tracked as a separate issue once Planner polling is field-validated.
- **Q3 — Webhook companion package.** Separate repo `mcp-server-microsoft-tasks-webhook` that ships the tunnel + receiver. Out-of-scope for the core MCP; design when there's demand.
