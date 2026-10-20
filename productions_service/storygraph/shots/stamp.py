"""Content-hash stamping for shot writes (shared by write tools and S7 lint remediation)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..repo import Repo
from ..schema import Shot
from .content_hash import compute_shot_content_hash, find_scene_clip
from .repair_state import mark_stale_and_reset

logger = logging.getLogger(__name__)


def stamp_content_hash(repo: Repo, prev: Shot | None, shot: Shot, actor: str) -> Shot:
    """Fingerprint `shot`; mark it stale when its render content differs from `prev`.

    Unchanged content keeps the previous staleness verdict, so a no-op regeneration
    neither invalidates approved clips nor clears an upstream-asset staleness flag.
    """
    scene = repo.get_scene(shot.scene_id)
    clip = find_scene_clip(scene.clips, shot.clip_index) if scene else None
    new_hash = compute_shot_content_hash(shot, clip)
    if prev is None:
        return shot.model_copy(update={"content_hash": new_hash})
    if prev.content_hash == new_hash:
        keep = {
            "stale": prev.stale,
            "stale_reason": prev.stale_reason,
            "repair_attempts": prev.repair_attempts,
            "needs_manual_edit": prev.needs_manual_edit,
            "manual_edit_reasons": list(prev.manual_edit_reasons),
        }
        return shot.model_copy(update={"content_hash": new_hash, **keep})
    reason = f"Shot content changed by {actor} regeneration"
    logger.info(
        "Shot content changed; existing clips invalidated",
        extra={
            "who": actor,
            "where": "shots.stamp.stamp_content_hash",
            "what": "shot_marked_stale",
            "when": datetime.now(UTC).isoformat(),
            "why": reason,
            "how": "sha256 render-content fingerprint mismatch",
            "project_id": repo.project_id,
            "shot_id": shot.id,
            "prev_hash": prev.content_hash,
            "new_hash": new_hash,
        },
    )
    hashed = shot.model_copy(update={"content_hash": new_hash})
    return mark_stale_and_reset(hashed, reason)
