# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Smoke test — proves the package imports and the CLI entry-point works.

Bootstrap-phase placeholder; replaced by real tool tests as the v0.1
read tools land.
"""

from __future__ import annotations

import microsoft_tasks_mcp
from microsoft_tasks_mcp.cli import main


def test_package_imports() -> None:
    assert microsoft_tasks_mcp.__version__ == "0.0.0"


def test_cli_main_returns_zero() -> None:
    assert main() == 0
