# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Console entry point. Wired into `[project.scripts]` in pyproject.toml.

Stub for v0.0.0 — the full CLI (login / logout / serve subcommands)
lands with the auth shim in the next milestone. For now `main()` prints
a placeholder so `uvx mcp-server-microsoft-tasks --help` doesn't 500
during the bootstrap phase.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Entry point invoked by the `mcp-server-microsoft-tasks` console script."""
    print(
        "mcp-server-microsoft-tasks v0.0.0 — pre-alpha bootstrap.\n"
        "The MCP server itself isn't wired up yet; see "
        "https://github.com/XMV-Solutions-GmbH/microsoft-tasks-mcp for status.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
