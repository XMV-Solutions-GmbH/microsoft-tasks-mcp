# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Smoke test — proves the package imports and the version string is set."""

from __future__ import annotations

import microsoft_tasks_mcp


def test_package_imports() -> None:
    assert microsoft_tasks_mcp.__version__ == "0.0.0"
