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

    def fake_interactive_login(*, profile: str) -> None:
        captured["profile"] = profile

    import microsoft_tasks_mcp.auth as auth_module

    monkeypatch.setattr(auth_module, "interactive_login", fake_interactive_login)

    rc = cli.main(["login", "--profile", "harness"])
    assert rc == 0
    assert captured == {"profile": "harness"}


def test_login_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_interactive_login(*, profile: str) -> None:
        captured["profile"] = profile

    import microsoft_tasks_mcp.auth as auth_module

    monkeypatch.setattr(auth_module, "interactive_login", fake_interactive_login)

    rc = cli.main(["login"])
    assert rc == 0
    assert captured == {"profile": "default"}


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
