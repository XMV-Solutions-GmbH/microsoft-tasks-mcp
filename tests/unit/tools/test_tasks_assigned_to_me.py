# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for tasks_assigned_to_me."""

from __future__ import annotations

import pytest
import respx

from microsoft_tasks_mcp.tools.tasks_assigned_to_me import assigned_to_me

GRAPH = "https://graph.microsoft.com/v1.0"
PLANNER_ME = f"{GRAPH}/me/planner/tasks"
TODO_LISTS = f"{GRAPH}/me/todo/lists"


def _patch_get_token(monkeypatch: pytest.MonkeyPatch, token: str = "AT") -> None:
    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.tasks_assigned_to_me.get_token",
        lambda profile: token,
    )


@respx.mock
def test_merges_planner_and_todo(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {
                    "id": "p1",
                    "title": "Ship release",
                    "planId": "plan1",
                    "bucketId": "b1",
                    "percentComplete": 0,
                    "assignments": {"u": {}},
                    "dueDateTime": "2026-05-15T00:00:00Z",
                }
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={
            "value": [
                {
                    "id": "t1",
                    "title": "Buy gift",
                    "status": "notStarted",
                    "dueDateTime": {
                        "dateTime": "2026-05-10T00:00:00",
                        "timeZone": "UTC",
                    },
                }
            ]
        }
    )
    out = assigned_to_me()["tasks"]
    sources = [task["source"] for task in out]
    assert "todo" in sources and "planner" in sources
    assert len(out) == 2


@respx.mock
def test_sorts_by_due_date_ascending(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {
                    "id": "p-late",
                    "title": "Later planner",
                    "percentComplete": 0,
                    "assignments": {},
                    "dueDateTime": "2026-06-01T00:00:00Z",
                },
                {
                    "id": "p-early",
                    "title": "Earlier planner",
                    "percentComplete": 0,
                    "assignments": {},
                    "dueDateTime": "2026-05-01T00:00:00Z",
                },
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me()["tasks"]
    assert [t["id"] for t in out] == ["p-early", "p-late"]


@respx.mock
def test_no_due_date_sorts_last(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {
                    "id": "p-undated",
                    "title": "No due",
                    "percentComplete": 0,
                    "assignments": {},
                },
                {
                    "id": "p-dated",
                    "title": "Dated",
                    "percentComplete": 0,
                    "assignments": {},
                    "dueDateTime": "2026-05-01T00:00:00Z",
                },
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me()["tasks"]
    assert [t["id"] for t in out] == ["p-dated", "p-undated"]


@respx.mock
def test_excludes_completed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {"id": "p-done", "percentComplete": 100, "assignments": {}},
                {"id": "p-open", "percentComplete": 50, "assignments": {}},
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me(include_completed=False)["tasks"]
    assert [t["id"] for t in out] == ["p-open"]


@respx.mock
def test_include_completed_returns_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {"id": "p-done", "percentComplete": 100, "assignments": {}},
                {"id": "p-open", "percentComplete": 50, "assignments": {}},
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me(include_completed=True)["tasks"]
    assert {t["id"] for t in out} == {"p-done", "p-open"}


@respx.mock
def test_todo_filter_added_for_default_include_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    todo_route = respx.get(f"{TODO_LISTS}/L1/tasks").respond(json={"value": []})
    assigned_to_me()
    url = (
        str(todo_route.calls.last.request.url)
        .replace("%24", "$")
        .replace("%20", " ")
        .replace("+", " ")
        .replace("%27", "'")
    )
    assert "$filter=status ne 'completed'" in url


def test_rejects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        assigned_to_me(limit=0)


@respx.mock
def test_handles_planner_403_via_per_source_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 on /me/planner/tasks no longer aborts the call — it's
    common in tenants where the user lacks Group.Read.All. The To Do
    half still returns. Behavior change in v0.4 per the cross-tenant
    fan-out RFC; previously this test asserted propagation."""
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(403, json={"error": "forbidden"})
    respx.get(TODO_LISTS).respond(
        json={
            "value": [{"id": "L1", "displayName": "Inbox"}],
        }
    )
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": "t1", "title": "X", "status": "notStarted"}]}
    )
    out = assigned_to_me()
    assert out["tasks"] and out["tasks"][0]["source"] == "todo"
    assert out["_skipped_profiles"] == []  # profile itself didn't fail; only the planner half


@respx.mock
def test_skips_individual_todo_list_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 on a single shared list is plausible and shouldn't kill
    the whole call."""
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "shared"}, {"id": "mine"}]})
    respx.get(f"{TODO_LISTS}/shared/tasks").respond(403, json={"error": "no"})
    respx.get(f"{TODO_LISTS}/mine/tasks").respond(
        json={
            "value": [
                {
                    "id": "t1",
                    "title": "ok",
                    "status": "notStarted",
                }
            ]
        }
    )
    out = assigned_to_me()["tasks"]
    assert [t["id"] for t in out] == ["t1"]


@respx.mock
def test_skips_planner_half_when_no_planner_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MS_TASKS_NO_PLANNER=true: cross-source must not hit /me/planner/tasks."""
    monkeypatch.setenv("MS_TASKS_NO_PLANNER", "true")
    _patch_get_token(monkeypatch)
    planner_route = respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": "t-todo", "title": "T", "status": "notStarted"}]}
    )
    out = assigned_to_me()["tasks"]
    assert planner_route.call_count == 0
    assert [t["source"] for t in out] == ["todo"]


@respx.mock
def test_per_source_split_respects_overall_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(
        json={
            "value": [{"id": f"p{i}", "percentComplete": 0, "assignments": {}} for i in range(20)]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": f"t{i}", "title": "X", "status": "notStarted"} for i in range(20)]}
    )
    out = assigned_to_me(limit=4)["tasks"]
    assert len(out) == 4


# ---------------------------------------------------------------------
# Cross-tenant fan-out (v0.4)
# ---------------------------------------------------------------------


def _patch_get_token_per_profile(monkeypatch: pytest.MonkeyPatch, tokens: dict[str, str]) -> None:
    """Tokens dispatch by profile name; raise NotAuthenticated for any unmapped."""

    def fake(profile: str) -> str:
        if profile not in tokens:
            raise RuntimeError(f"profile {profile!r} has no cached token")
        return tokens[profile]

    monkeypatch.setattr(
        "microsoft_tasks_mcp.tools.tasks_assigned_to_me.get_token",
        fake,
    )


@respx.mock
def test_fanout_two_profiles_tags_each_envelope_with_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token_per_profile(monkeypatch, {"acme": "AT-A", "globex": "AT-G"})
    # Both profiles share the same Graph base — respx matches by URL, not auth header.
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={
            "value": [
                {"id": "t-a", "title": "Task A", "status": "notStarted"},
            ]
        }
    )
    out = assigned_to_me(profiles=["acme", "globex"])
    profiles = sorted({task["profile"] for task in out["tasks"]})
    assert profiles == ["acme", "globex"]
    assert out["_skipped_profiles"] == []


@respx.mock
def test_fanout_skipped_profile_logged_in_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile whose token retrieval fails must surface in
    _skipped_profiles but must not abort the rest."""
    _patch_get_token_per_profile(monkeypatch, {"good": "AT"})
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": []})
    out = assigned_to_me(profiles=["good", "missing"])
    skipped_names = {entry["profile"] for entry in out["_skipped_profiles"]}
    assert skipped_names == {"missing"}
    assert "missing" not in {task["profile"] for task in out["tasks"]}


@respx.mock
def test_fanout_all_profiles_failing_returns_empty_tasks_with_full_skip_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_get_token_per_profile(monkeypatch, {})
    out = assigned_to_me(profiles=["a", "b", "c"])
    assert out["tasks"] == []
    assert {entry["profile"] for entry in out["_skipped_profiles"]} == {"a", "b", "c"}


@respx.mock
def test_single_profile_default_path_still_stamps_profile_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `profiles` is omitted, the single `profile` arg is used and
    each envelope is stamped with that name."""
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": "t1", "title": "X", "status": "notStarted"}]}
    )
    out = assigned_to_me(profile="my-tenant")
    assert all(task["profile"] == "my-tenant" for task in out["tasks"])


@respx.mock
def test_fanout_merge_sort_orders_across_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sorting by due_date is applied AFTER merge — so an early task
    from profile B can appear before a later task from profile A."""
    _patch_get_token_per_profile(monkeypatch, {"a": "T1", "b": "T2"})
    respx.get(PLANNER_ME).respond(
        json={
            "value": [
                {
                    "id": "p1",
                    "title": "Planner-late",
                    "percentComplete": 0,
                    "assignments": {},
                    "dueDateTime": "2026-12-01T00:00:00Z",
                }
            ]
        }
    )
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={
            "value": [
                {
                    "id": "t1",
                    "title": "Todo-early",
                    "status": "notStarted",
                    "dueDateTime": {"dateTime": "2026-05-15T00:00:00", "timeZone": "UTC"},
                }
            ]
        }
    )
    out = assigned_to_me(profiles=["a", "b"], limit=10)
    titles = [t["title"] for t in out["tasks"]]
    todo_indices = [i for i, t in enumerate(titles) if t == "Todo-early"]
    planner_indices = [i for i, t in enumerate(titles) if t == "Planner-late"]
    assert min(todo_indices) < max(planner_indices)


@respx.mock
def test_fanout_per_profile_limit_split(monkeypatch: pytest.MonkeyPatch) -> None:
    """`limit` is split per profile (limit // n_profiles) with a floor of 1."""
    _patch_get_token_per_profile(monkeypatch, {"a": "T1", "b": "T2"})
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    # Each profile's call gets a per-profile limit; the test cares
    # that we don't return more than `limit` total.
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={
            "value": [{"id": f"t{i}", "title": f"T{i}", "status": "notStarted"} for i in range(20)]
        }
    )
    out = assigned_to_me(profiles=["a", "b"], limit=4)
    assert len(out["tasks"]) <= 4


def test_fanout_invalid_limit_still_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get_token(monkeypatch)
    with pytest.raises(ValueError, match="limit must be positive"):
        assigned_to_me(profiles=["a"], limit=0)


@respx.mock
def test_fanout_explicit_empty_profiles_list_falls_back_to_single(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`profiles=[]` is the same as None — caller asked for nothing
    specific so we use the default profile."""
    _patch_get_token(monkeypatch)
    respx.get(PLANNER_ME).respond(json={"value": []})
    respx.get(TODO_LISTS).respond(json={"value": [{"id": "L1"}]})
    respx.get(f"{TODO_LISTS}/L1/tasks").respond(
        json={"value": [{"id": "t1", "title": "X", "status": "notStarted"}]}
    )
    out = assigned_to_me(profiles=[])
    assert all(task["profile"] == "default" for task in out["tasks"])
