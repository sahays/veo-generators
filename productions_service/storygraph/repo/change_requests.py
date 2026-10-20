"""ChangeRequest lifecycle: close Critic CRs once their target shot is fixed.

A Critic CR on a shot (filed when QA retries are exhausted) is resolved when the shot gets
an APPROVED GenerationRun, is re-rendered (a new attempt supersedes the flagged one; a new
failure files a fresh CR), or its render-relevant spec changes (`Shot.content_hash`).
Strict assembly still gates on shot readiness, so closing a CR never unblocks a bad clip.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Final, Literal

from ..schema import ChangeRequest, Role, Status
from ..store.base import GraphStore
from ..store.codec import decode, encode

logger = logging.getLogger(__name__)

CrTrigger = Literal["approved_run", "rerendered", "spec_regenerated"]
_STATUS_BY_TRIGGER: Final[dict[str, Status]] = {
    "approved_run": Status.APPROVED,
    "rerendered": Status.SUPERSEDED,
    "spec_regenerated": Status.SUPERSEDED,
}


def _open_critic_crs(store: GraphStore, target_node_id: str) -> list[ChangeRequest]:
    rows = store.query(
        "change_requests", filters=[("target_node_id", "==", target_node_id)]
    )
    crs = [decode(r, ChangeRequest) for r in rows]
    return [cr for cr in crs if cr.resolution == "open" and cr.from_role == Role.CRITIC]


def close_critic_change_requests(
    store: GraphStore, target_node_id: str, trigger: CrTrigger
) -> list[str]:
    """Resolve every open Critic CR on `target_node_id`; returns the closed CR ids."""
    closed: list[str] = []
    for cr in _open_critic_crs(store, target_node_id):
        updated = cr.model_copy(
            update={
                "resolution": "accepted",
                "status": _STATUS_BY_TRIGGER[trigger],
                "version": cr.version + 1,
            }
        )
        store.set("change_requests", updated.id, encode(updated))
        closed.append(cr.id)
    if closed:
        logger.info(
            "Critic ChangeRequests closed",
            extra={
                "who": "storygraph.repo",
                "where": "repo.change_requests",
                "what": "change_requests_closed",
                "when": datetime.now(UTC).isoformat(),
                "why": trigger,
                "how": "target shot fixed -> resolution=accepted",
                "target_node_id": target_node_id,
                "change_request_ids": closed,
            },
        )
    return closed
