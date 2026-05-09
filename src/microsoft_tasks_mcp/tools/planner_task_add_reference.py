# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_task_add_reference — attach a URL reference to a profile-owned Planner task.

PATCH /planner/tasks/{taskId}/details, merging one entry into the
`references` open-type dict. Refuses NOT_OWNED_BY_PROFILE. Surfaces
EXTERNALLY_MODIFIED on details-ETag mismatch (412).
"""

from __future__ import annotations

from typing import Any

import httpx

from microsoft_tasks_mcp.auth import get_token
from microsoft_tasks_mcp.task_registry import TaskRegistry
from microsoft_tasks_mcp.tools._common import (
    auth_headers,
    graph_planner_base,
    tenant_id_from_token,
)
from microsoft_tasks_mcp.tools._references import (
    encode_reference_url,
    validate_reference_url,
)
from microsoft_tasks_mcp.tools._shape import planner_envelope
from microsoft_tasks_mcp.tools._writes_common import (
    ExternallyModifiedError,
    require_owned_by_profile,
)


def add_planner_task_reference(
    task_id: str,
    url: str,
    *,
    alias: str | None = None,
    type_hint: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Add a URL reference to a profile-owned Planner task.

    `url` must be `http://` or `https://`. `alias` is the human label
    Graph displays in the Planner UI (defaults to the URL itself);
    `type_hint` is a Microsoft-classified type string — common values
    are `"Word"`, `"Excel"`, `"PowerPoint"`, `"PDF"`, `"Other"`.
    Graph accepts any string here, so we pass it through.

    Returns the unified envelope of the task plus a `references` list
    folded in (so the agent can confirm the new state in one round-trip).
    """
    if not task_id or not task_id.strip():
        raise ValueError("planner_task_add_reference requires a non-empty task_id")
    normalised_url = validate_reference_url(url)

    task_id_s = task_id.strip()
    reg = registry if registry is not None else TaskRegistry(profile)
    require_owned_by_profile(
        registry=reg,
        graph_id=task_id_s,
        expected_source="planner",
    )

    token = get_token(profile)
    tenant_id = tenant_id_from_token(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        # Step 1: GET /details to capture the current details ETag.
        # Graph requires `If-Match` on the details PATCH. The details
        # ETag is independent from the task ETag we keep in the registry.
        details_response = client.get(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}/details",
            headers=auth_headers(token),
        )
        details_response.raise_for_status()
        details = details_response.json()
        details_etag = details.get("@odata.etag") if isinstance(details, dict) else None

        # Step 2: PATCH the references dict — merging one new entry.
        encoded = encode_reference_url(normalised_url)
        entry: dict[str, Any] = {
            "@odata.type": "microsoft.graph.externalReference",
        }
        if alias is not None:
            entry["alias"] = alias
        if type_hint is not None:
            entry["type"] = type_hint

        patch_headers: dict[str, str] = {
            **auth_headers(token),
            "Content-Type": "application/json",
        }
        if isinstance(details_etag, str):
            patch_headers["If-Match"] = details_etag
        patch_response = client.patch(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}/details",
            headers=patch_headers,
            json={"references": {encoded: entry}},
        )
        if patch_response.status_code == 412:
            raise ExternallyModifiedError(task_id_s)
        patch_response.raise_for_status()

        # Step 3: re-fetch the task + details for a clean return value.
        task_response = client.get(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}",
            headers=auth_headers(token),
        )
        task_response.raise_for_status()
        envelope = planner_envelope(task_response.json(), tenant_id=tenant_id)

        details_after = client.get(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}/details",
            headers=auth_headers(token),
        )
        details_after.raise_for_status()
        envelope["references"] = _extract_references(details_after.json().get("references"))
        envelope["details_etag"] = details_after.json().get("@odata.etag")
    finally:
        if http is None:
            client.close()

    return envelope


def _extract_references(raw: Any) -> list[dict[str, Any]]:
    """Flatten Graph's references dict to a list, decoding the URL key.

    The raw shape is `{<encoded_url>: {alias, type, ...}}`. We return
    `[{url, alias, type}, ...]` with the URL fully decoded so the agent
    can use it directly.
    """
    if not isinstance(raw, dict):
        return []
    # Imported here to keep the public-API import surface narrow.
    from microsoft_tasks_mcp.tools._references import decode_reference_url

    out: list[dict[str, Any]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        out.append(
            {
                "url": decode_reference_url(key),
                "alias": value.get("alias"),
                "type": value.get("type"),
            }
        )
    return out
