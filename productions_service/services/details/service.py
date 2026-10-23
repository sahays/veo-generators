"""On-demand detail endpoints that keep heavy history out of the first-paint snapshot.

- `shot_run_history`: every render attempt of one shot, full detail, newest first.
- `audit_log_page`: cursor-paginated audit tail.
- `scene_detail`: a full scene node (interaction steps are omitted from the snapshot).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from storygraph.repo import Repo
from storygraph.schema import AuditEntry
from storygraph.store.codec import decode
from storygraph.store.url_signing import sign_all

from ..runtime import get_repo, load_runtime_config
from ..snapshot.shaping import run_detail, select_active_runs
from .audit_page import decode_cursor, paginate, query_window

logger = logging.getLogger(__name__)


def _repo(project_id: str) -> Repo:
    repo = get_repo(project_id, cfg=load_runtime_config())
    if repo.get_project_meta() is None:
        raise HTTPException(status_code=404, detail="Production not found")
    return repo


def _log(what: str, project_id: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "productions_service",
            "where": "services.details.service",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": "studio lazy-loaded detail (kept out of the snapshot)",
            "how": "single filtered/paginated store query + batched cached URL signing",
            "project_id": project_id,
            **extra,
        },
    )


def shot_run_history(project_id: str, shot_id: str) -> dict[str, Any]:
    """All attempts for `shot_id` (newest attempt first) plus the active run id."""
    repo = _repo(project_id)
    runs = repo.list_generation_runs(shot_id=shot_id)
    active = select_active_runs(runs).get(shot_id)
    signed = sign_all(repo.blobs, [r.output_video_uri or "" for r in runs])
    ordered = sorted(runs, key=lambda r: (r.attempt, r.created_at), reverse=True)
    _log("shot_run_history_served", project_id, shot_id=shot_id, runs=len(runs))
    return {
        "shot_id": shot_id,
        "active_run_id": active.id if active else None,
        "runs": [run_detail(r, signed) for r in ordered],
    }


def audit_log_page(project_id: str, limit: int, cursor: str | None) -> dict[str, Any]:
    """One newest-first page of audit entries and the cursor for the next (older) page."""
    repo = _repo(project_id)
    parsed = decode_cursor(cursor)
    filters, row_limit = query_window(parsed, limit)
    rows = repo.store.query(
        "audit_log", filters=filters or None, order_by="-created_at", limit=row_limit
    )
    page, nxt = paginate(rows, parsed, limit)
    _log(
        "audit_log_page_served", project_id, entries=len(page), has_more=nxt is not None
    )
    return {
        "entries": [decode(r, AuditEntry).model_dump(mode="json") for r in page],
        "next_cursor": nxt.encode() if nxt else None,
    }


def scene_detail(project_id: str, scene_id: str) -> dict[str, Any]:
    """Full scene node, including interaction steps and clip scripts."""
    scene = _repo(project_id).get_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
    return scene.model_dump(mode="json")
