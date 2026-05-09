# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the shared `tools/_common.py` helpers.

Pins the audit-trail invariant from
docs/spikes/2026-05-08-v02-drafts-spikes.md § 2: every outbound Graph
request from any `ol_*` tool carries `Authorization: Bearer ...` AND
`User-Agent: mcp-server-microsoft-tasks/<version>`. Hard-coding both header
keys here makes a regression visible the moment someone replaces
`auth_headers` with a hand-rolled dict.
"""

from __future__ import annotations

import base64
import json

from microsoft_tasks_mcp import __version__
from microsoft_tasks_mcp.tools._common import (
    GRAPH_BASE,
    USER_AGENT,
    auth_headers,
    planner_web_url,
    tenant_id_from_token,
)


def _make_jwt(payload: dict[str, object]) -> str:
    """Build a fake unsigned JWT with the given payload — header +
    signature parts are placeholder garbage, just enough to pass
    `tenant_id_from_token`'s shape check."""

    def b64(d: dict[str, object] | bytes) -> str:
        if isinstance(d, dict):
            d = json.dumps(d).encode()
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    header = b64({"alg": "RS256", "typ": "JWT"})
    body = b64(payload)
    return f"{header}.{body}.signaturePlaceholder"


def test_graph_base_url_is_v1() -> None:
    assert GRAPH_BASE == "https://graph.microsoft.com/v1.0"


def test_user_agent_includes_package_version() -> None:
    assert USER_AGENT == f"mcp-server-microsoft-tasks/{__version__}"


def test_user_agent_starts_with_package_name() -> None:
    """Compliance reviewers should see the server name first in
    raw HTTP diagnostics — not a Python-version prefix."""
    assert USER_AGENT.startswith("mcp-server-microsoft-tasks/")


def test_auth_headers_carry_bearer_token() -> None:
    headers = auth_headers("ABC.DEF.GHI")
    assert headers["Authorization"] == "Bearer ABC.DEF.GHI"


def test_auth_headers_carry_user_agent() -> None:
    headers = auth_headers("AT")
    assert headers["User-Agent"] == USER_AGENT


def test_auth_headers_only_authoritative_keys() -> None:
    """Catch accidental extra headers. Tools that need additional
    headers should layer them on top, not have them sneak in via the
    shared helper."""
    headers = auth_headers("AT")
    assert set(headers.keys()) == {"Authorization", "User-Agent"}


# ---------------------------------------------------------------------
# tenant_id_from_token
# ---------------------------------------------------------------------


def test_tenant_id_extracted_from_jwt_tid_claim() -> None:
    token = _make_jwt({"tid": "11111111-2222-3333-4444-555555555555", "upn": "x@y"})
    assert tenant_id_from_token(token) == "11111111-2222-3333-4444-555555555555"


def test_tenant_id_returns_none_when_tid_missing() -> None:
    token = _make_jwt({"upn": "x@y"})
    assert tenant_id_from_token(token) is None


def test_tenant_id_returns_none_when_tid_not_a_string() -> None:
    token = _make_jwt({"tid": 12345})
    assert tenant_id_from_token(token) is None


def test_tenant_id_returns_none_when_tid_empty() -> None:
    token = _make_jwt({"tid": ""})
    assert tenant_id_from_token(token) is None


def test_tenant_id_returns_none_for_garbage_token() -> None:
    assert tenant_id_from_token("not-a-jwt") is None


def test_tenant_id_returns_none_for_two_part_token() -> None:
    """JWT must have exactly three dot-separated parts."""
    assert tenant_id_from_token("aa.bb") is None


def test_tenant_id_returns_none_when_payload_not_object() -> None:
    """Payload that decodes to a list (not a dict) is malformed."""
    payload = base64.urlsafe_b64encode(b"[1,2,3]").rstrip(b"=").decode()
    token = f"header.{payload}.sig"
    assert tenant_id_from_token(token) is None


def test_tenant_id_returns_none_when_payload_not_json() -> None:
    """Payload that's not valid JSON must not raise."""
    payload = base64.urlsafe_b64encode(b"not json").rstrip(b"=").decode()
    token = f"header.{payload}.sig"
    assert tenant_id_from_token(token) is None


# ---------------------------------------------------------------------
# planner_web_url
# ---------------------------------------------------------------------


def test_planner_web_url_canonical_format() -> None:
    url = planner_web_url(
        "11111111-2222-3333-4444-555555555555",
        "task-abc-123",
    )
    assert (
        url
        == "https://tasks.office.com/11111111-2222-3333-4444-555555555555/Home/Task/task-abc-123"
    )
