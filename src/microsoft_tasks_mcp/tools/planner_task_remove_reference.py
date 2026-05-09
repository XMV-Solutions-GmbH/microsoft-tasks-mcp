# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""planner_task_remove_reference — detach a URL reference from a profile-owned Planner task.

PATCH /planner/tasks/{taskId}/details with `{references: {<encoded>: null}}`
— Graph's documented form for removing a single open-type entry.
Idempotent on a missing URL: returns the unchanged task envelope
without raising. Refuses NOT_OWNED_BY_PROFILE; surfaces
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


def remove_planner_task_reference(
    task_id: str,
    url: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
    registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Remove a URL reference from a profile-owned Planner task.

    Idempotent on a URL that isn't currently a reference — Graph's
    PATCH semantics treat the patch as a merge, so setting a missing
    key to null is a no-op. We still go through the PATCH to refresh
    the returned envelope cleanly.
    """
    if not task_id or not task_id.strip():
        raise ValueError("planner_task_remove_reference requires a non-empty task_id")
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
        details_response = client.get(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}/details",
            headers=auth_headers(token),
        )
        details_response.raise_for_status()
        details = details_response.json()
        details_etag = details.get("@odata.etag") if isinstance(details, dict) else None

        encoded = encode_reference_url(normalised_url)
        patch_headers: dict[str, str] = {
            **auth_headers(token),
            "Content-Type": "application/json",
        }
        if isinstance(details_etag, str):
            patch_headers["If-Match"] = details_etag
        patch_response = client.patch(
            f"{graph_planner_base()}/planner/tasks/{task_id_s}/details",
            headers=patch_headers,
            json={"references": {encoded: None}},
        )
        if patch_response.status_code == 412:
            raise ExternallyModifiedError(task_id_s)
        patch_response.raise_for_status()

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
        # Imported here to keep the public-API import surface narrow.
        from microsoft_tasks_mcp.tools.planner_task_add_reference import _extract_references

        envelope["references"] = _extract_references(details_after.json().get("references"))
        envelope["details_etag"] = details_after.json().get("@odata.etag")
    finally:
        if http is None:
            client.close()

    return envelope
