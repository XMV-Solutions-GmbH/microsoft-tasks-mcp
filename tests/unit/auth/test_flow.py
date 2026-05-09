# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the auth/flow shim.

Pins:

- DEFAULT_CLIENT_ID matches the registered Entra app (`mcp-server-microsoft-tasks`
  in the XMV tenant). If it changes, the test fails — and that's the
  reminder to update the deployed app or coordinate the rollout.
- The base scope list is read-only — no Tasks.ReadWrite by default, so
  the consent prompt stays read-only on a default install.
- `writes_enabled()` flips on `TASKS_ALLOW_WRITES=true`-ish values; off
  on absent / falsy / unrecognised values.
- `resolve_scopes()` is read at call time, not at module import, so
  test-time env flips work without re-import.
"""

from __future__ import annotations

import pytest

from microsoft_tasks_mcp.auth import flow


def test_default_client_id_matches_registered_entra_app() -> None:
    # Registered via `az ad app create` in the XMV tenant on 2026-05-09.
    # Multi-tenant, public client, Device Code flow enabled.
    assert flow.DEFAULT_CLIENT_ID == "0faf4ede-b330-4034-a49f-cbb47eac0ccd"


def test_default_authority_tenant_is_organizations() -> None:
    assert flow.DEFAULT_AUTHORITY_TENANT == "organizations"


def test_base_scopes_are_read_only_plus_planner_enumeration() -> None:
    """The default install must not request Tasks.ReadWrite. The consent
    screen stays read-only; the user opts in via TASKS_ALLOW_WRITES."""
    assert flow._BASE_SCOPES == (
        "Tasks.Read",
        "Group.Read.All",
        "User.Read",
        "offline_access",
    )
    # Backwards-compat alias for callers that import at module-load time.
    assert flow.DEFAULT_SCOPES == flow._BASE_SCOPES


def test_writes_enabled_default_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    assert flow.writes_enabled() is False


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES", "on", "ON"])
def test_writes_enabled_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, value)
    assert flow.writes_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "maybe", "TASKS_ALLOW_WRITES"])
def test_writes_enabled_falsy_or_unrecognised_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, value)
    assert flow.writes_enabled() is False


def test_resolve_scopes_writes_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    assert "Tasks.ReadWrite" not in flow.resolve_scopes()
    assert flow.resolve_scopes() == flow._BASE_SCOPES


def test_resolve_scopes_writes_enabled_appends_readwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "true")
    scopes = flow.resolve_scopes()
    assert "Tasks.Read" in scopes
    assert "Tasks.ReadWrite" in scopes
    assert "Group.Read.All" in scopes
    assert "User.Read" in scopes
    assert "offline_access" in scopes


def test_resolve_scopes_is_call_time_not_import_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flip the env var without reimporting; resolve_scopes must observe the change."""
    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    before = flow.resolve_scopes()
    assert "Tasks.ReadWrite" not in before

    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "1")
    after = flow.resolve_scopes()
    assert "Tasks.ReadWrite" in after


# ---------------------------------------------------------------------
# planner_disabled / MS_TASKS_NO_PLANNER
# ---------------------------------------------------------------------


def test_planner_disabled_default_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(flow.NO_PLANNER_ENV, raising=False)
    assert flow.planner_disabled() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "ON"])
def test_planner_disabled_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(flow.NO_PLANNER_ENV, value)
    assert flow.planner_disabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "maybe"])
def test_planner_disabled_falsy_or_unrecognised(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(flow.NO_PLANNER_ENV, value)
    assert flow.planner_disabled() is False


def test_resolve_scopes_drops_group_read_when_planner_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(flow.NO_PLANNER_ENV, "true")
    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    scopes = flow.resolve_scopes()
    assert "Group.Read.All" not in scopes
    # Other read scopes still present
    assert "Tasks.Read" in scopes
    assert "User.Read" in scopes
    assert "offline_access" in scopes


def test_resolve_scopes_planner_disabled_with_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two flags compose independently: NO_PLANNER + ALLOW_WRITES =
    no Group.Read.All, with Tasks.ReadWrite included."""
    monkeypatch.setenv(flow.NO_PLANNER_ENV, "true")
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "true")
    scopes = flow.resolve_scopes()
    assert "Group.Read.All" not in scopes
    assert "Tasks.ReadWrite" in scopes
    assert "Tasks.Read" in scopes


def test_resolve_scopes_default_includes_group_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default install (no env flags) requests Group.Read.All —
    Planner is on by default."""
    monkeypatch.delenv(flow.NO_PLANNER_ENV, raising=False)
    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    assert "Group.Read.All" in flow.resolve_scopes()


def test_lib_re_exports_are_present() -> None:
    """The shim must re-export the shared library's exception types
    so callers don't need to know the lib's internals."""
    assert flow.AuthorizationDeniedError is not None
    assert flow.DeviceCodeExpiredError is not None
    assert flow.RefreshTokenInvalidError is not None
    assert flow.DeviceCodeChallenge is not None
    assert flow.DeviceCodeError is not None
    assert flow.CachedToken is not None


def test_request_device_code_delegates_with_resolved_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_request_device_code(*, client_id, tenant, scopes, http):  # type: ignore[no-untyped-def]
        captured["client_id"] = client_id
        captured["tenant"] = tenant
        captured["scopes"] = scopes
        return ("device-code-stub", object())

    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    monkeypatch.setattr(flow, "_lib_request_device_code", fake_request_device_code)

    flow.request_device_code()

    assert captured["client_id"] == flow.DEFAULT_CLIENT_ID
    assert captured["tenant"] == flow.DEFAULT_AUTHORITY_TENANT
    assert captured["scopes"] == flow._BASE_SCOPES


def test_request_device_code_explicit_scopes_override_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit scopes arg bypasses resolve_scopes so callers can test
    boundary cases (e.g. forcing Tasks.ReadWrite without setting the env)."""
    captured: dict[str, object] = {}

    def fake_request_device_code(*, client_id, tenant, scopes, http):  # type: ignore[no-untyped-def]
        captured["scopes"] = scopes
        return ("device-code-stub", object())

    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    monkeypatch.setattr(flow, "_lib_request_device_code", fake_request_device_code)

    forced = ("Tasks.Read", "Tasks.ReadWrite")
    flow.request_device_code(scopes=forced)

    assert captured["scopes"] == forced
