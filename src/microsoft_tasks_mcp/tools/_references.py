# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Helpers for the Planner externalReferences (`/details.references`) collection.

Per Microsoft Graph: references are an Open Type dict on
`plannerTaskDetails`, keyed by URL. OData property names can't contain
`. : % @ #`, so the URL key must be percent-encoded (and percent-encoded
percent: `%` → `%25` first). The value is an `externalReference` object.

Add: PATCH /details with `{"references": {<encoded_url>: {<entry>}}}`,
including `If-Match`. Graph performs a dictionary merge — existing
keys not in the patch are unchanged.

Remove: PATCH /details with `{"references": {<encoded_url>: null}}`.
"""

from __future__ import annotations

# Per Graph docs: . : % @ # are forbidden in OData open-type property
# names. We percent-encode them (and only them) to keep the URL
# round-trippable and minimise diff against the canonical form.
_ENCODE_TABLE = str.maketrans(
    {
        "%": "%25",  # MUST be first — the others below produce % chars
        ".": "%2E",
        ":": "%3A",
        "@": "%40",
        "#": "%23",
    }
)
_DECODE_PAIRS = (
    ("%2E", "."),
    ("%3A", ":"),
    ("%40", "@"),
    ("%23", "#"),
    ("%25", "%"),  # MUST be last — undoes the leading-% replacement
)

_ALLOWED_SCHEMES = ("http://", "https://")


def encode_reference_url(url: str) -> str:
    """Encode a URL for use as a Planner externalReferences dict key.

    Encoding done in two passes — first `%` (so we don't double-encode
    the `%XX` sequences we're about to introduce), then `.`, `:`, `@`,
    `#`. The result is what Graph expects on the wire and is what comes
    back unchanged on a read.
    """
    encoded = url.replace("%", "%25")
    return encoded.replace(".", "%2E").replace(":", "%3A").replace("@", "%40").replace("#", "%23")


def decode_reference_url(key: str) -> str:
    """Reverse of `encode_reference_url`. Used on read so the agent
    sees the canonical URL, not the OData-safe form."""
    out = key
    for pat, repl in _DECODE_PAIRS:
        out = out.replace(pat, repl)
    return out


def validate_reference_url(url: str) -> str:
    """Normalise + validate a reference URL.

    Returns the trimmed URL on success. Raises `ValueError` if empty,
    not a string, or not an `http://` / `https://` URL — Graph rejects
    other schemes (`onenote:`, `mailto:`, etc.) at the wire layer, so
    we catch that locally.
    """
    if not isinstance(url, str):
        raise ValueError("reference url must be a string")
    trimmed = url.strip()
    if not trimmed:
        raise ValueError("reference url must not be empty")
    if not trimmed.lower().startswith(_ALLOWED_SCHEMES):
        raise ValueError(
            f"reference url must start with http:// or https:// (Planner refs accept "
            f"only HTTP/HTTPS schemes), got {url!r}",
        )
    return trimmed
