"""Pure, deterministic content fingerprint for the render-relevant parts of a `Shot`.

The hash lets the render stage and final assembly tell whether an existing
`GenerationRun` was rendered from the *current* shot content or from an older
screenplay/director pass that reused the same deterministic shot id.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..clips.models import ClipScript
from ..schema import GenerationRun, Shot

# Fields that change what Omni renders. Volatile bookkeeping (version, stale,
# stale_reason, created_at, created_by, status, run ids) is intentionally excluded.
_SHOT_RENDER_FIELDS: frozenset[str] = frozenset(
    {
        "clip_index",
        "duration_s",
        "beats",
        "cast",
        "prop_ids",
        "camera",
        "look",
        "dialogue_ids",
        "location_id",
        "location_appearance_id",
        "continue_from_last_frame",
    }
)


def _clip_payload(clip: ClipScript | None) -> dict[str, Any] | None:
    if clip is None:
        return None
    return {"omni_prompt": clip.omni_prompt, "duration_s": clip.duration_s}


def compute_shot_content_hash(shot: Shot, clip: ClipScript | None = None) -> str:
    """Return a sha256 hex digest over the render-relevant content of `shot` (+ its clip)."""
    payload: dict[str, Any] = {
        "shot": shot.model_dump(mode="json", include=set(_SHOT_RENDER_FIELDS)),
        "clip": _clip_payload(clip),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_scene_clip(
    clips: list[ClipScript], clip_index: int | None
) -> ClipScript | None:
    """Return the scene clip linked 1:1 to a shot via `clip_index`, if any."""
    if clip_index is None:
        return None
    return next((c for c in clips if c.clip_index == clip_index), None)


def run_matches_shot(run: GenerationRun, shot: Shot) -> bool:
    """True when `run` was rendered from the shot's current content.

    Legacy runs (no recorded hash) only count for legacy shots (no hash either).
    """
    return run.shot_content_hash == shot.content_hash


__all__ = ["compute_shot_content_hash", "find_scene_clip", "run_matches_shot"]
