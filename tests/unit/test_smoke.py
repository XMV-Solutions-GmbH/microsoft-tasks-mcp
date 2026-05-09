# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Smoke test — proves the package imports and the version string is set."""

from __future__ import annotations

import microsoft_tasks_mcp


def test_package_imports() -> None:
    """Sanity: package imports + version follows the documented shape."""
    assert microsoft_tasks_mcp.__version__
    parts = microsoft_tasks_mcp.__version__.split(".")
    assert len(parts) >= 3, microsoft_tasks_mcp.__version__
