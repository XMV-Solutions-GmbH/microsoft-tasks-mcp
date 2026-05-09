# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Command-line entry point.

Three commands:

- `mcp-server-microsoft-tasks login [--profile NAME]` — interactive
  Device Code flow, persists the resulting tokens to the configured
  TokenStore. Run once per profile; subsequent MCP-server starts use
  the cached refresh token silently.
- `mcp-server-microsoft-tasks logout [--profile NAME]` — clears cached
  credentials.
- `mcp-server-microsoft-tasks` (no command) — starts the MCP server on
  stdio. (v0.0.0 stub: emits a status message until Issue #5 lands the
  real server skeleton.)

The login/logout subcommands deliberately mirror the `gh auth login` /
`gh auth logout` pattern: auth setup is out-of-band, the running MCP
process never blocks for human interaction.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from microsoft_tasks_mcp import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-server-microsoft-tasks",
        description=(
            "MCP server for Microsoft Tasks (Microsoft Planner + Microsoft "
            "To Do, unified) — read-only by default, writes opt-in, never "
            "modifies tasks the agent didn't create itself."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    login_p = subparsers.add_parser(
        "login",
        help="Sign in via Microsoft Device Code flow and cache the refresh token.",
    )
    login_p.add_argument(
        "--profile",
        default="default",
        help="Profile name (namespace for token cache). Default: 'default'.",
    )

    logout_p = subparsers.add_parser(
        "logout",
        help="Remove cached credentials for a profile.",
    )
    logout_p.add_argument(
        "--profile",
        default="default",
        help="Profile name. Default: 'default'.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the right subcommand.

    Returns the process exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "login":
        from microsoft_tasks_mcp.auth import interactive_login

        interactive_login(profile=args.profile)
        return 0

    if args.command == "logout":
        from microsoft_tasks_mcp.auth.store import get_token_store

        get_token_store().delete(args.profile)
        return 0

    # No subcommand — would start the MCP server on stdio. The server
    # skeleton lands with Issue #5; until then this path is a status
    # message rather than a non-functional stdio server.
    print(
        f"mcp-server-microsoft-tasks {__version__} — pre-alpha.\n"
        "The MCP server skeleton isn't wired up yet (Issue #5). The CLI\n"
        "subcommands `login` and `logout` work today; run with `--help`\n"
        "for usage. Track status at\n"
        "https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp/issues",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
