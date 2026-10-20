"""Re-map a scene's shots after S7 split/re-balanced its clips (deterministic first).

Every clip that descends from an existing clip inherits that shot's camera, look, cast
staging and props. Only brand-new clips (the second half of a split) get a director draft —
from the LLM when available, otherwise the deterministic fallback blocking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ...adapters.mock import MockLLMClient
from ...schema import ClipScript, Role, Shot
from ...tools.registry import ToolContext
from ...tools.role_helpers import (
    DirectorSceneOutput,
    ShotDraft,
    normalize_indian_epic_names,
)
from ...views import scene_view
from ..runner import run_role
from .director import (
    build_director_prompt,
    build_scene_blocking,
    persist_clip_shot,
    prune_orphan_shots,
)
from .director_clips import fallback_drafts, match_drafts_to_clips

logger = logging.getLogger(__name__)


def _carry(shot: Shot, clip: ClipScript) -> ShotDraft:
    """Draft that keeps `shot`'s camera/look/staging for (possibly re-indexed) `clip`."""
    return ShotDraft(
        shot_id=shot.id,
        index_in_scene=clip.clip_index,
        story_order=shot.story_order,
        clip_index=clip.clip_index,
        duration_s=clip.duration_s,
        location_id=shot.location_id,
        cast=list(shot.cast),
        prop_ids=list(shot.prop_ids),
        camera=shot.camera,
        look=shot.look,
        entry_motion_vector=shot.entry_motion_vector,
        exit_motion_vector=shot.exit_motion_vector,
    )


def _new_drafts(
    ctx: ToolContext, scene_id: str, new: list[int], mock_llm: MockLLMClient | None
) -> dict[int, ShotDraft]:
    """Director drafts for the brand-new clips only (camera/look); fallback when no LLM."""
    sview = scene_view(ctx.repo, scene_id)
    blk, chars, props = build_scene_blocking(ctx, sview)
    clips = sview.scene.clips
    fb = DirectorSceneOutput(
        shots=fallback_drafts(scene_id, sview.scene.location_id, blk.lead_id, clips)
    )
    story = normalize_indian_epic_names(ctx.repo.get_source_text() or "")
    note = [f"clip(s) {new} are new after a clip split; author camera/look for them"]
    res = run_role(
        role=Role.DIRECTOR,
        ctx=ctx,
        user_prompt=build_director_prompt(story, blk, chars, props, note),
        output_schema=DirectorSceneOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: fb,
    )
    drafts = match_drafts_to_clips(list(res.output.shots or fb.shots), clips)
    return {
        c.clip_index: d
        for c, d in zip(clips, drafts, strict=True)
        if d is not None and c.clip_index in new
    }


def remap_scene_shots(
    ctx: ToolContext,
    scene_id: str,
    origin: dict[int, int | None],
    mock_llm: MockLLMClient | None = None,
) -> list[str]:
    """Persist exactly one shot per (new) clip of `scene_id`; returns the kept shot ids."""
    old = {s.clip_index: s for s in ctx.repo.list_shots(scene_id=scene_id)}
    sview = scene_view(ctx.repo, scene_id)
    clips = sview.scene.clips
    carried = {
        c.clip_index: _carry(old[o], c)
        for c in clips
        if (o := origin.get(c.clip_index)) is not None and o in old
    }
    new = [c.clip_index for c in clips if c.clip_index not in carried]
    drafts = {**(_new_drafts(ctx, scene_id, new, mock_llm) if new else {}), **carried}
    blk, _, _ = build_scene_blocking(ctx, sview)
    kept = [
        persist_clip_shot(ctx, blk, pos, clip, drafts.get(clip.clip_index))
        for pos, clip in enumerate(clips, start=1)
    ]
    prune_orphan_shots(ctx, scene_id, set(kept))
    logger.info(
        "Scene shots re-mapped after S7 clip remediation",
        extra={
            "who": str(Role.DIRECTOR),
            "where": "director_remap.remap_scene_shots",
            "what": f"{len(kept)} shots ({len(new)} new) for scene {scene_id}",
            "when": datetime.now(UTC).isoformat(),
            "why": "spec lint split or re-balanced the scene's clips",
            "how": "carry camera/look from origin shots; director draft for new clips",
        },
    )
    return kept
