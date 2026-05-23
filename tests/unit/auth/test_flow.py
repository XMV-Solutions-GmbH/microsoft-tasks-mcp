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


def test_default_authority_tenant_is_common() -> None:
    """Since the personal-account-support PR, the default authority is
    `common` — accepts both AzureAD (work/school) and personal MSAs.
    The XMV Entra app's signInAudience was widened to match."""
    assert flow.DEFAULT_AUTHORITY_TENANT == "common"


def test_default_scopes_backwards_compat_shape() -> None:
    """v0.4 callers that imported DEFAULT_SCOPES at module-load time
    still see the read-only shape (Tasks.Read + Group.Read.All etc.).
    Runtime-aware scope resolution lives in resolve_scopes()."""
    assert flow.DEFAULT_SCOPES == (
        "Tasks.Read",
        "Group.Read.All",
        "User.Read",
        "offline_access",
    )


# ---------------------------------------------------------------------
# writes_enabled / TASKS_ALLOW_WRITES — strict env-var parsing (v0.5)
# ---------------------------------------------------------------------


def test_writes_enabled_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    with pytest.raises(flow.TasksConsentNotConfiguredError, match="not set"):
        flow.writes_enabled()


@pytest.mark.parametrize("value", ["true", "True", "TRUE", " true "])
def test_writes_enabled_true_accepts_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, value)
    assert flow.writes_enabled() is True


@pytest.mark.parametrize("value", ["false", "FALSE", " false "])
def test_writes_enabled_false_accepts_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, value)
    assert flow.writes_enabled() is False


@pytest.mark.parametrize("value", ["1", "yes", "on", "", "0", "no", "off", "garbage"])
def test_writes_enabled_strict_rejects_legacy_and_other_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """v0.5 breaking change: only exactly 'true' / 'false' accepted.
    Legacy v0.4 truthy values (1/yes/on) and any other string raise."""
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, value)
    with pytest.raises(flow.TasksConsentNotConfiguredError, match="TASKS_ALLOW_WRITES"):
        flow.writes_enabled()


def test_resolve_scopes_writes_false_returns_readonly_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASKS_ALLOW_WRITES=false → consent screen requests Tasks.Read only
    (no Tasks.ReadWrite). Group.Read.All still there since NO_PLANNER unset."""
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "false")
    monkeypatch.delenv(flow.NO_PLANNER_ENV, raising=False)
    scopes = flow.resolve_scopes()
    assert "Tasks.Read" in scopes
    assert "Tasks.ReadWrite" not in scopes
    assert "Group.Read.All" in scopes
    assert "User.Read" in scopes
    assert "offline_access" in scopes


def test_resolve_scopes_writes_true_replaces_with_readwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASKS_ALLOW_WRITES=true → Tasks.ReadWrite REPLACES Tasks.Read
    (ReadWrite subsumes Read; the consent screen shows one tasks line,
    not two)."""
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "true")
    monkeypatch.delenv(flow.NO_PLANNER_ENV, raising=False)
    scopes = flow.resolve_scopes()
    assert "Tasks.ReadWrite" in scopes
    assert "Tasks.Read" not in scopes
    assert "Group.Read.All" in scopes


def test_resolve_scopes_is_call_time_not_import_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flip the env var without reimporting; resolve_scopes must observe the change."""
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "false")
    before = flow.resolve_scopes()
    assert "Tasks.ReadWrite" not in before

    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "true")
    after = flow.resolve_scopes()
    assert "Tasks.ReadWrite" in after


def test_resolve_scopes_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(flow.ALLOW_WRITES_ENV, raising=False)
    with pytest.raises(flow.TasksConsentNotConfiguredError):
        flow.resolve_scopes()


def test_validate_consent_config_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "true")
    assert flow.validate_consent_config() is True
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "false")
    assert flow.validate_consent_config() is False


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
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "false")
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
    no Group.Read.All, with Tasks.ReadWrite replacing Tasks.Read."""
    monkeypatch.setenv(flow.NO_PLANNER_ENV, "true")
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "true")
    scopes = flow.resolve_scopes()
    assert "Group.Read.All" not in scopes
    assert "Tasks.ReadWrite" in scopes
    assert "Tasks.Read" not in scopes  # replaced, not appended


def test_resolve_scopes_planner_enabled_with_writes_false_includes_group_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit-false install (writes=false, Planner default-on) requests
    Group.Read.All for Planner enumeration."""
    monkeypatch.delenv(flow.NO_PLANNER_ENV, raising=False)
    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "false")
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

    monkeypatch.setenv(flow.ALLOW_WRITES_ENV, "false")
    monkeypatch.delenv(flow.NO_PLANNER_ENV, raising=False)
    monkeypatch.setattr(flow, "_lib_request_device_code", fake_request_device_code)

    flow.request_device_code()

    assert captured["client_id"] == flow.DEFAULT_CLIENT_ID
    assert captured["tenant"] == flow.DEFAULT_AUTHORITY_TENANT
    # writes=false → read-only scope stack
    assert captured["scopes"] == flow.resolve_scopes()
    assert "Tasks.ReadWrite" not in captured["scopes"]
    assert "Tasks.Read" in captured["scopes"]


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


# ---------------------------------------------------------------------
# account_type → tenant mapping (#54)
# ---------------------------------------------------------------------


def test_account_type_to_tenant_personal_maps_to_consumers() -> None:
    """Personal MSAs route through Microsoft Identity's /consumers
    authority — the only path that returns the personal Device Code
    landing page (microsoft.com/link)."""
    assert flow.account_type_to_tenant(flow.ACCOUNT_TYPE_PERSONAL) == "consumers"


def test_account_type_to_tenant_work_maps_to_organizations() -> None:
    """Work/school accounts route through /organizations, NOT /common.
    /common returns the work/school landing page even for personal-
    capable apps; we use /organizations for an explicit choice."""
    assert flow.account_type_to_tenant(flow.ACCOUNT_TYPE_WORK_OR_SCHOOL) == "organizations"


@pytest.mark.parametrize("bad", ["", "common", "consumers", "Personal", "WORK_OR_SCHOOL", "privat"])
def test_account_type_to_tenant_rejects_unknown(bad: str) -> None:
    """Strict per #54 — typos must raise loudly, never silently fall
    through to a wrong endpoint."""
    with pytest.raises(ValueError, match="account_type"):
        flow.account_type_to_tenant(bad)


def test_valid_account_types_constant_matches_two_values() -> None:
    """The literal tuple is the public contract that callers
    (CLI choices, MCP-tool descriptions) hang their UI off."""
    assert flow.VALID_ACCOUNT_TYPES == ("personal", "work_or_school")
    assert flow.ACCOUNT_TYPE_PERSONAL == "personal"
    assert flow.ACCOUNT_TYPE_WORK_OR_SCHOOL == "work_or_school"


# ---------------------------------------------------------------------
# LoginAccountTypeRequiredError (#54)
# ---------------------------------------------------------------------


def test_login_account_type_required_error_default_message_includes_both_values() -> None:
    """The default message is what the MCP-tool layer surfaces to the
    agent. It MUST name both valid values verbatim — the agent uses
    those strings to retry the tool call."""
    err = flow.LoginAccountTypeRequiredError()
    msg = str(err)
    assert "personal" in msg
    assert "work_or_school" in msg


def test_login_account_type_required_error_mentions_outlook_com() -> None:
    """Help text should hint at concrete account-domain examples so
    the user can recognise their account kind."""
    err = flow.LoginAccountTypeRequiredError()
    assert "outlook.com" in str(err)


def test_login_account_type_required_error_mentions_planner_caveat() -> None:
    """Tasks-mcp-specific: the error message should mention that Planner
    needs work/school. Helps the user choose correctly even if they have
    both account types and aren't sure which to use."""
    assert "Planner" in str(flow.LoginAccountTypeRequiredError())


def test_login_account_type_required_error_has_agent_instructions_marker() -> None:
    """Stable marker `AGENT_INSTRUCTIONS:` lets MCP clients pattern-
    match the error and route it to the user-elicitation UI."""
    assert "AGENT_INSTRUCTIONS:" in str(flow.LoginAccountTypeRequiredError())


def test_login_account_type_required_error_accepts_custom_message() -> None:
    """Callers can override with profile-specific text; default stays the safe one."""
    custom = flow.LoginAccountTypeRequiredError("custom override text")
    assert str(custom) == "custom override text"
