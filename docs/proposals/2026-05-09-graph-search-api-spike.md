<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Proposal: Graph Search API for tasks_search

- **Status:** Withdrawn
- **Authors:** `David Koller <david.koller@xmv.de>`
- **Date drafted:** `2026-05-09`
- **Date accepted:** `—`
- **Tracking issue:** [#29](https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues/29)

## Context

`tasks_search` in v0.1 was implemented client-side: enumerate the user's lists / plans, fetch each list's tasks, substring-match locally. Per [`docs/app-concept.md`](../app-concept.md) § Q1 this was a deliberate v0.1 choice — it works fine at typical task volumes (hundreds per user) without any extra scopes — but the open question was whether [Microsoft Graph Search](https://learn.microsoft.com/en-us/graph/search-concept-overview) (`POST /search/query`) could later replace it for higher volumes / better relevance ranking.

This proposal captures the empirical spike conducted against the harness account on the live `https://graph.microsoft.com/v1.0/search/query` endpoint.

## Decision

**Withdrawn.** The Microsoft Graph Search API does not support task entity types and would in any case require admin-consent scopes that conflict with v0.3's `MS_TASKS_NO_PLANNER` non-admin-friendly mode. Client-side `tasks_search` stays as the canonical implementation.

## Empirical findings

Tested 2026-05-09 against `d.koller@xmv.de` with the v0.3.0 token (`Tasks.Read` + `Tasks.ReadWrite` + `Group.Read.All` + `User.Read` + `offline_access`):

```text
POST https://graph.microsoft.com/v1.0/search/query
{
  "requests": [{
    "entityTypes": ["plannerTask"],
    "query": {"queryString": "harness"},
    "from": 0,
    "size": 10
  }]
}
→ 400 BadRequest: "The call failed, please try again."
```

`plannerTask` is not in the [supported entity-types list](https://learn.microsoft.com/en-us/graph/api/resources/searchrequest#properties): only `message`, `event`, `drive`, `driveItem`, `externalItem`, `list`, `listItem`, `site`, `bookmark`, `acronym`, `qna`, `chatMessage`. Neither Microsoft Planner tasks nor Microsoft To Do tasks are searchable through this endpoint.

A control call with `entityTypes: ["driveItem"]` (a supported type) returned 403 Forbidden, demanding `Files.Read.All` / `Sites.Read.All` / similar admin-consent scopes. Even if Microsoft did add `plannerTask` to the supported list later, the access pattern likely follows the same admin-consent-required model — which directly conflicts with the goal of `MS_TASKS_NO_PLANNER` as a non-admin-friendly mode.

## Alternatives considered

### Alternative A: Wait for Microsoft to add task entity types

Possible long-term, but no public roadmap signal exists. Not worth blocking on.

### Alternative B: Use the consumer Graph Search at `/me/search/query`

Same endpoint shape; no different entity-type support; rejected for the same reason.

### Alternative C: Index tasks ourselves into a local searchable store

Out of scope for an MCP server: significant ongoing maintenance, sync correctness becomes a problem, no clear payoff vs. the client-side enumeration that already works.

## Consequences

- **Positive:** No more uncertainty about whether to migrate `tasks_search`. The current client-side implementation is the canonical answer for the foreseeable future.
- **Negative:** None — the status quo continues.
- **Neutral but worth knowing:** If at some point Microsoft Graph adds `plannerTask` / `todoTask` as searchable entity types, this proposal should be re-opened (i.e. a *new* proposal would supersede this one) and we'd benchmark client-side vs. Graph Search at a real-world task volume to decide.

## Implementation notes

None — this is a Withdrawn spike. The v0.1 client-side `tasks_search` implementation in [`src/microsoft_tasks_mcp/tools/tasks_search.py`](../../src/microsoft_tasks_mcp/tools/tasks_search.py) remains unchanged.

## References

- [Microsoft Graph Search overview](https://learn.microsoft.com/en-us/graph/search-concept-overview)
- [`searchRequest` resource type](https://learn.microsoft.com/en-us/graph/api/resources/searchrequest)
- `docs/app-concept.md` § "Open tech-spike questions" Q1
