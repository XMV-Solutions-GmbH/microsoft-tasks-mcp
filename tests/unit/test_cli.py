# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the CLI entry point."""

from __future__ import annotations

from typing import Any

import pytest

from microsoft_tasks_mcp import cli


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "mcp-server-microsoft-tasks" in out
    assert "login" in out
    assert "logout" in out


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--version"])
    assert exc_info.value.code == 0


def test_login_dispatches_to_interactive_login(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["profile"] = profile
        captured["account_type"] = account_type

    import microsoft_tasks_mcp.auth as auth_module

    monkeypatch.setattr(auth_module, "interactive_login", fake_interactive_login)

    rc = cli.main(["login", "--profile", "harness", "--account-type", "work_or_school"])
    assert rc == 0
    assert captured == {"profile": "harness", "account_type": "work_or_school"}


def test_login_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["profile"] = profile
        captured["account_type"] = account_type

    import microsoft_tasks_mcp.auth as auth_module

    monkeypatch.setattr(auth_module, "interactive_login", fake_interactive_login)

    rc = cli.main(["login", "--account-type", "personal"])
    assert rc == 0
    assert captured == {"profile": "default", "account_type": "personal"}


def test_login_account_type_personal_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--account-type personal` is passed verbatim into interactive_login —
    test seam for the personal-account routing."""
    captured: dict[str, Any] = {}

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["account_type"] = account_type

    import microsoft_tasks_mcp.auth as auth_module

    monkeypatch.setattr(auth_module, "interactive_login", fake_interactive_login)
    assert cli.main(["login", "--account-type", "personal"]) == 0
    assert captured["account_type"] == "personal"


def test_login_account_type_invalid_choice_rejected_by_argparse() -> None:
    """argparse `choices` enforces the two-value contract at parse time;
    a typo never reaches the auth layer."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["login", "--account-type", "privat"])
    assert excinfo.value.code == 2


def test_login_no_account_type_no_env_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --account-type AND without TASKS_TENANT_ID, the CLI
    exits 2 with the agent-readable elicit-user message on stderr.
    This is the v0.6 onboarding default."""
    monkeypatch.delenv("TASKS_TENANT_ID", raising=False)
    # Use the REAL interactive_login (no monkeypatch).
    assert cli.main(["login"]) == 2
    err = capsys.readouterr().err
    assert "account_type" in err
    assert "personal" in err
    assert "work_or_school" in err


def test_login_env_var_satisfies_requirement_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backwards-compat: TASKS_TENANT_ID set → CLI accepts no flag and
    delegates to interactive_login with account_type=None."""
    monkeypatch.setenv("TASKS_TENANT_ID", "consumers")
    captured: dict[str, Any] = {}

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["account_type"] = account_type

    import microsoft_tasks_mcp.auth as auth_module

    monkeypatch.setattr(auth_module, "interactive_login", fake_interactive_login)
    assert cli.main(["login"]) == 0
    assert captured["account_type"] is None


def test_logout_clears_token_for_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    class _FakeStore:
        def delete(self, profile: str) -> None:
            deleted.append(profile)

    import microsoft_tasks_mcp.auth.store as store_module

    monkeypatch.setattr(store_module, "get_token_store", lambda: _FakeStore())

    rc = cli.main(["logout", "--profile", "harness"])
    assert rc == 0
    assert deleted == ["harness"]


def test_no_subcommand_starts_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """No subcommand → the MCP server on stdio. Verify dispatch to
    `microsoft_tasks_mcp.server.run` rather than asserting on stdio
    behaviour (which would actually block the test)."""
    called = {"run": False}

    def fake_run() -> None:
        called["run"] = True

    import microsoft_tasks_mcp.server as server_module

    monkeypatch.setattr(server_module, "run", fake_run)

    rc = cli.main([])
    assert rc == 0
    assert called["run"] is True
