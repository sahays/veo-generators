"""DIRECTOR role agent runner (`director_agent`): exactly one camera-blocked Shot per Omni clip."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from ...adapters.mock import MockLLMClient
from ...clips.limits import camera_rules_text, feedback_block
from ...presets.models import ResolvedProductionPresets
from ...schema import (
    CastInShot,
    ClipScript,
    DialogueLine,
    Entity,
    EntityType,
    InteractionStep,
    Role,
    ShotLook,
)
from ...state import state_at
from ...tools import write_tools as wt
from ...tools.registry import ToolContext
from ...tools.role_helpers import (
    DirectorSceneOutput,
    ShotDraft,
    deduplicate_cast_positions,
    normalize_indian_epic_names,
)
from ...views import SceneView, scene_view
from ..runner import RoleRunResult, run_role
from .director_clips import beats_for_clip, fallback_drafts, match_drafts_to_clips
from .director_look import (
    default_look,
    look_constraints_block,
    merge_look,
    resolve_bundle,
)

logger = logging.getLogger(__name__)


@dataclass
class _SceneBlocking:
    """Per-scene context shared by every shot the director persists."""

    sview: SceneView
    lead_id: str
    char_ids: set[str]
    prop_ids: set[str]
    ev_ids: list[str]
    dlg_by_id: dict[str, DialogueLine]
    steps: dict[int, InteractionStep]
    base_order: int
    bundle: ResolvedProductionPresets
    prev_positions: dict[str, str]
    lighting_anchor: ShotLook | None = None


def _resolve_shot_cast(
    sh: ShotDraft, blk: _SceneBlocking, shot_dlgs: list[str]
) -> dict[str, CastInShot]:
    """Enforce scene-wide character permanence, `speaking` iff speaking, and 180-degree slots."""
    speaker_ids = {blk.dlg_by_id[d].speaker_id for d in shot_dlgs if d in blk.dlg_by_id}
    cast_by_id = {
        c.entity_id: c.model_copy(
            update={"appearance_id": "", "speaking": c.entity_id in speaker_ids}
        )
        for c in sh.cast
        if c.entity_id in blk.char_ids
    }
    if not cast_by_id:
        cast_by_id[blk.lead_id] = CastInShot(
            entity_id=blk.lead_id,
            position="center",
            framing="MCU",
            speaking=blk.lead_id in speaker_ids,
        )
    for cid in [*sorted(speaker_ids & blk.char_ids), *sorted(blk.char_ids)]:
        if cid not in cast_by_id:
            cast_by_id[cid] = CastInShot(
                entity_id=cid,
                position=blk.prev_positions.get(cid, "right"),  # type: ignore[arg-type]
                framing="MCU" if cid in speaker_ids else "MS",
                speaking=cid in speaker_ids,
            )
    return deduplicate_cast_positions(cast_by_id, blk.prev_positions)


def _resolve_props(
    ctx: ToolContext,
    sh: ShotDraft,
    blk: _SceneBlocking,
    cast_ids: list[str],
    order: int,
) -> list[str]:
    """Scene prop closure plus any scene prop a cast member holds at `order`."""
    props = list(
        dict.fromkeys(
            [*(p for p in sh.prop_ids if p in blk.prop_ids), *sorted(blk.prop_ids)]
        )
    )
    for cid in cast_ids:
        held = state_at(ctx.repo, cid, order).get("holding")
        if held and held in blk.prop_ids and held not in props:
            props.append(held)
    return props


def persist_clip_shot(
    ctx: ToolContext,
    blk: _SceneBlocking,
    pos: int,
    clip: ClipScript,
    draft: ShotDraft | None,
) -> str:
    """Persist the Shot for `clip`: duration, dialogue, beats, and clip link are set in code."""
    sh = (
        draft
        or fallback_drafts(
            blk.sview.scene.id, blk.sview.scene.location_id, blk.lead_id, [clip]
        )[0]
    )
    order = blk.base_order + min(pos - 1, max(0, len(blk.sview.events) - 1))
    shot_dlgs = [d for d in clip.dialogue_line_ids if d in blk.dlg_by_id]
    cast_by_id = _resolve_shot_cast(sh, blk, shot_dlgs)
    props = _resolve_props(ctx, sh, blk, list(cast_by_id), order)
    anchor = blk.lighting_anchor.lighting if blk.lighting_anchor else None
    look = merge_look(
        sh.look,
        anchor,
        default_look(blk.sview.style_guide, blk.bundle, blk.sview.scene, pos),
    )
    blk.lighting_anchor = blk.lighting_anchor or look
    shot_id = f"shot_{blk.sview.scene.id}_{pos:02d}"
    wt.put_shot(
        ctx,
        shot_id=shot_id,
        scene_id=blk.sview.scene.id,
        index_in_scene=pos,
        story_order=order,
        duration_s=clip.duration_s,
        location_id=blk.sview.scene.location_id,
        covers_event_ids=blk.ev_ids,
        cast=list(cast_by_id.values()),
        prop_ids=props,
        camera=sh.camera,
        beats=beats_for_clip(clip, blk.steps, [*cast_by_id, *props]),
        dialogue_ids=shot_dlgs,
        continue_from_last_frame=(pos > 1),
        look=look,
        clip_index=clip.clip_index,
    )
    return shot_id


def build_director_prompt(
    story_context: str,
    blk: _SceneBlocking,
    chars: list[Entity],
    props: list[Entity],
    feedback: Sequence[str] = (),
) -> str:
    """Build the user prompt for `DIRECTOR` camera + look authoring (one shot per clip)."""
    sc = blk.sview.scene
    clip_list = [
        c.model_dump(exclude={"opening_state", "closing_state"}) for c in sc.clips
    ]
    dlg_list = [
        {"id": d.id, "speaker_id": d.speaker_id, "text": d.text}
        for d in blk.sview.dialogue_lines
    ]
    return (
        f"Directorial Style Preset ({blk.bundle.director_style.label}): {blk.bundle.director_style.instruction_prompt}\n\n"
        f"Full Story Context:\n{story_context}\n\n"
        f"Scene '{sc.id}' (location_id='{sc.location_id}') is arranged by the Screenwriter into {len(sc.clips)} Omni clips (8–10s each). "
        f"Return EXACTLY {len(sc.clips)} shots — one per clip, with `clip_index` set to that clip's index. "
        "Do not change clip duration, dialogue assignment or action; you own `camera`, `look`, `cast` staging and `prop_ids`.\n"
        f"CLIPS: {clip_list}\n"
        f"Valid character entity_ids: {[{'id': c.id, 'name': c.canonical_name} for c in chars]}\n"
        f"Valid prop_ids: {[{'id': p.id, 'name': p.canonical_name} for p in props]}\n"
        f"Dialogue lines: {dlg_list}\n"
        + look_constraints_block(blk.sview.style_guide, blk.bundle)
        + "RULES: 1. Include ALL scene characters in `cast` and ALL scene props in `prop_ids` in every shot. "
        "2. Preserve 180-degree screen positions (`left`/`center`/`right`) across consecutive shots. "
        "3. Vary shot size/angle/lens across consecutive shots to cut cleanly. "
        "4. For emotional moments describe subtle glistening eyes — never 'tearful starlight sparkles'. "
        f"5. {camera_rules_text()}\n\n"
        + feedback_block(feedback, "SPEC LINTER REJECTED THE PREVIOUS SHOTS")
        + f"SCENE VIEW:\n{blk.sview.model_dump_json(exclude={'shots'})}"
    )


def _sync_scene_event_orders(
    ctx: ToolContext, sview: SceneView
) -> tuple[int, list[str]]:
    """Normalize `story_order` on `sview.events` and return `(base_order, ev_ids)`."""
    base_order = sview.scene.index * 10
    for e_idx, ev in enumerate(sview.events):
        if ev.story_order != base_order + e_idx:
            ctx.repo.put_event(
                ev.model_copy(update={"story_order": base_order + e_idx})
            )
    return base_order, [e.id for e in sview.events]


def _scene_cast_and_props(
    ctx: ToolContext, sview: SceneView
) -> tuple[list[Entity], list[Entity]]:
    chars = [
        e for e in sview.entities_in_scene if e.entity_type == EntityType.CHARACTER
    ]
    chars = chars or ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    props = [e for e in sview.entities_in_scene if e.entity_type == EntityType.OBJECT]
    if not props and len(ctx.repo.list_scenes()) <= 1:
        props = ctx.repo.list_entities(entity_type=EntityType.OBJECT)
    return chars, props


def prune_orphan_shots(ctx: ToolContext, scene_id: str, keep: set[str]) -> None:
    """Delete shots of `scene_id` that no longer map to a clip (clip count shrank)."""
    for sh in ctx.repo.list_shots(scene_id=scene_id):
        if sh.id not in keep:
            ctx.repo.delete_shot(sh.id)
            logger.info(
                "Pruned orphan shot after clip re-arrangement",
                extra={
                    "who": "director",
                    "where": "director.prune_orphan_shots",
                    "what": "delete_shot",
                    "shot_id": sh.id,
                    "scene_id": scene_id,
                    "why": "no matching clip_index",
                    "how": "repo.delete_shot",
                },
            )


def build_scene_blocking(
    ctx: ToolContext, sview: SceneView
) -> tuple[_SceneBlocking, list[Entity], list[Entity]]:
    """Per-scene blocking context (+ scene characters and props) for persisting shots."""
    chars, props = _scene_cast_and_props(ctx, sview)
    base_order, ev_ids = _sync_scene_event_orders(ctx, sview)
    blk = _SceneBlocking(
        sview=sview,
        lead_id=chars[0].id if chars else "char_arjun",
        char_ids={c.id for c in chars},
        prop_ids={p.id for p in props},
        ev_ids=ev_ids,
        dlg_by_id={d.id: d for d in sview.dialogue_lines},
        steps={s.step_index: s for s in sview.scene.interaction_steps},
        base_order=base_order,
        bundle=resolve_bundle(ctx.repo),
        prev_positions={},
    )
    return blk, chars, props


def run_director_for_scene(
    ctx: ToolContext,
    scene_id: str,
    mock_llm: MockLLMClient | None = None,
    feedback: Sequence[str] = (),
) -> RoleRunResult:
    """Run DIRECTOR to camera-block and light exactly one Shot per screenwriter clip of `scene_id`."""
    sview = scene_view(ctx.repo, scene_id)
    blk, chars, props = build_scene_blocking(ctx, sview)
    clips = sview.scene.clips
    fb = DirectorSceneOutput(
        shots=fallback_drafts(scene_id, sview.scene.location_id, blk.lead_id, clips)
    )
    story_context = normalize_indian_epic_names(ctx.repo.get_source_text() or "")
    res = run_role(
        role=Role.DIRECTOR,
        ctx=ctx,
        user_prompt=build_director_prompt(story_context, blk, chars, props, feedback),
        output_schema=DirectorSceneOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: fb,
    )
    drafts = match_drafts_to_clips(list(res.output.shots or fb.shots), clips)
    kept = {
        persist_clip_shot(ctx, blk, pos, clip, draft)
        for pos, (clip, draft) in enumerate(zip(clips, drafts, strict=True), start=1)
    }
    prune_orphan_shots(ctx, scene_id, kept)
    return res
