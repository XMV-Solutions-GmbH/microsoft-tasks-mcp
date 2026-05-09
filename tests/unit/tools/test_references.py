# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the Planner externalReferences encoding/validation helpers."""

from __future__ import annotations

import pytest

from microsoft_tasks_mcp.tools._references import (
    decode_reference_url,
    encode_reference_url,
    validate_reference_url,
)

# ---------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://contoso.sharepoint.com/teams/agile/AnnualReport.pptx",
        "http://example.com/page",
        "https://www.example.com/path/with/slashes/file.html",
        # Real-world URLs include @ in mailto-style anchors and # in fragments
        "https://example.com/users/alice@example.com#section",
        # %-bearing URLs (already-encoded segments)
        "https://example.com/path%20with%20spaces",
    ],
)
def test_encode_then_decode_round_trips(url: str) -> None:
    assert decode_reference_url(encode_reference_url(url)) == url


def test_encode_includes_all_required_substitutions() -> None:
    out = encode_reference_url("http://x.y:8080/path@a#b")
    assert "." not in out
    assert ":" not in out
    assert "@" not in out
    assert "#" not in out


def test_encode_handles_existing_percent_first() -> None:
    """Existing % in the URL must be encoded BEFORE we insert new %XX
    sequences, otherwise we'd double-encode."""
    encoded = encode_reference_url("https://x.y/a%2Eb")
    decoded = decode_reference_url(encoded)
    assert decoded == "https://x.y/a%2Eb"


# ---------------------------------------------------------------------
# validate_reference_url
# ---------------------------------------------------------------------


def test_validate_accepts_http_url() -> None:
    assert validate_reference_url("http://example.com/x") == "http://example.com/x"


def test_validate_accepts_https_url() -> None:
    assert validate_reference_url("https://example.com/x") == "https://example.com/x"


def test_validate_strips_whitespace() -> None:
    assert validate_reference_url("  https://example.com/x  ") == "https://example.com/x"


def test_validate_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_reference_url("")


def test_validate_rejects_whitespace_only() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_reference_url("   ")


def test_validate_rejects_non_string() -> None:
    with pytest.raises(ValueError, match="must be a string"):
        validate_reference_url(42)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "onenote:https://example.com/page",
        "mailto:alice@example.com",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "/relative/path",
        "no-scheme.example.com",
    ],
)
def test_validate_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(ValueError, match="http:// or https://"):
        validate_reference_url(url)


def test_validate_accepts_uppercase_scheme() -> None:
    """Some clients normalise to HTTPS; allow that."""
    assert validate_reference_url("HTTPS://example.com") == "HTTPS://example.com"
