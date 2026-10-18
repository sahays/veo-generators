"""DIRECTOR role agent runner (`director_agent`)."""

from __future__ import annotations

import re

from ...adapters.mock import MockLLMClient
from ...schema import (
    ActionBeat,
    CameraSpec,
    CastInShot,
    DialogueLine,
    Entity,
    EntityType,
    Role,
)
from ...state import state_at
from ...tools import write_tools as wt
from ...tools.registry import ToolContext
from ...tools.role_helpers import (
    DirectorSceneOutput,
    ShotDraft,
    deduplicate_cast_positions,
    expand_overbudget_shot_buckets,
    normalize_indian_epic_names,
    partition_scene_dialogues,
)
from ...views import SceneView, scene_view
from ..runner import RoleRunResult, run_role


def _build_fallback_shot_one(
    scene_id: str,
    sview: SceneView,
    lead_id: str,
    lead_name: str,
    chars: list[Entity],
    prop_id_list: list[str],
    ev_ids: list[str],
    dlg_ids: list[str],
    base_order: int,
) -> ShotDraft:
    """Build the establishing Shot 1 draft for `_build_director_fallback`."""
    loc_name = (
        sview.location.canonical_name if sview.location else sview.scene.location_id
    )
    cast_list = [
        CastInShot(
            entity_id=lead_id, position="center", framing="MCU", speaking=bool(dlg_ids)
        ),
        *[
            CastInShot(entity_id=c.id, position="right", framing="MS", speaking=False)
            for c in chars[1:2]
        ],
    ]
    cam = CameraSpec(
        shot_size="WS" if sview.scene.index == 1 else "MCU",
        angle="eye",
        movement="dolly_in",
        lens_mm=35,
        focus_target_id=lead_id,
    )
    beats = [
        ActionBeat(
            t_start_s=0.0,
            t_end_s=2.5,
            description=f"{lead_name} enters {loc_name}: {sview.scene.summary}",
            subject_ids=[lead_id],
        ),
        ActionBeat(
            t_start_s=2.5,
            t_end_s=5.0,
            description=f"{lead_name} reacts in {loc_name}.",
            subject_ids=[lead_id, *prop_id_list],
        ),
    ]
    return ShotDraft(
        shot_id=f"shot_{scene_id}_01",
        index_in_scene=1,
        story_order=base_order,
        covers_event_ids=ev_ids,
        duration_s=5.0,
        location_id=sview.scene.location_id,
        cast=cast_list,
        prop_ids=prop_id_list,
        camera=cam,
        beats=beats,
        dialogue_ids=dlg_ids[:1],
        continue_from_last_frame=False,
    )


def _build_fallback_shot_two(
    scene_id: str,
    sview: SceneView,
    lead_id: str,
    prop_id_list: list[str],
    ev_ids: list[str],
    dlg_ids: list[str],
    base_order: int,
) -> ShotDraft:
    """Build the close-up Shot 2 draft for `_build_director_fallback`."""
    loc_name = (
        sview.location.canonical_name if sview.location else sview.scene.location_id
    )
    cam = CameraSpec(
        shot_size="CU",
        angle="low",
        movement="static",
        lens_mm=50,
        focus_target_id=prop_id_list[0] if prop_id_list else lead_id,
    )
    beats = [
        ActionBeat(
            t_start_s=0.0,
            t_end_s=5.0,
            description=f"Dramatic close-up in {loc_name} as the scene reaches its climax.",
            subject_ids=[lead_id, *prop_id_list],
        )
    ]
    return ShotDraft(
        shot_id=f"shot_{scene_id}_02",
        index_in_scene=2,
        story_order=base_order + 1,
        covers_event_ids=ev_ids,
        duration_s=5.0,
        location_id=sview.scene.location_id,
        cast=[
            CastInShot(
                entity_id=lead_id,
                position="center",
                framing="CU",
                speaking=len(dlg_ids) > 1,
            )
        ],
        prop_ids=prop_id_list,
        camera=cam,
        beats=beats,
        dialogue_ids=dlg_ids[1:],
        continue_from_last_frame=True,
    )


def _build_director_fallback(
    scene_id: str,
    sview: SceneView,
    chars: list[Entity],
    prop_id_list: list[str],
    ev_ids: list[str],
    dlg_ids: list[str],
    base_order: int,
) -> DirectorSceneOutput:
    """Build a deterministic 2-shot `DirectorSceneOutput` fallback for `scene_id`."""
    lead_id = chars[0].id if chars else "char_arjun"
    lead_name = chars[0].canonical_name if chars else "Arjun"
    return DirectorSceneOutput(
        shots=[
            _build_fallback_shot_one(
                scene_id,
                sview,
                lead_id,
                lead_name,
                chars,
                prop_id_list,
                ev_ids,
                dlg_ids,
                base_order,
            ),
            _build_fallback_shot_two(
                scene_id, sview, lead_id, prop_id_list, ev_ids, dlg_ids, base_order
            ),
        ]
    )


def _select_shot_dialogues_and_duration(
    sh: ShotDraft,
    shot_dlgs: list[str],
    dlg_by_id: dict[str, DialogueLine],
) -> tuple[list[str], float]:
    """Compute shot duration for the partitioned `shot_dlgs` without dropping lines."""
    dur = max(4.0, min(float(sh.duration_s or 5.0), 8.0))
    total_words = sum(
        len(dlg_by_id[did].text.split()) for did in shot_dlgs if did in dlg_by_id
    )
    if total_words > 0:
        dur = max(dur, min(8.0, round((total_words / 2.5) + 0.5, 1)))
    return shot_dlgs, dur


def _resolve_shot_cast(
    sh: ShotDraft,
    lead_id: str,
    valid_char_ids: set[str],
    shot_dlgs: list[str],
    dlg_by_id: dict[str, DialogueLine],
    prev_positions: dict[str, str],
) -> dict[str, CastInShot]:
    """Normalize shot cast, strictly set `speaking` iff speaking in `shot_dlgs`, and deduplicate positions."""
    speaker_ids = {dlg_by_id[did].speaker_id for did in shot_dlgs if did in dlg_by_id}
    cast_by_id = {
        c.entity_id: c.model_copy(
            update={"appearance_id": "", "speaking": c.entity_id in speaker_ids}
        )
        for c in sh.cast
        if c.entity_id in valid_char_ids
    }
    if not cast_by_id:
        cast_by_id[lead_id] = CastInShot(
            entity_id=lead_id,
            position="center",
            framing="MCU",
            speaking=lead_id in speaker_ids,
        )
    for did in shot_dlgs:
        sp_id = dlg_by_id[did].speaker_id
        if sp_id in valid_char_ids and sp_id not in cast_by_id:
            cast_by_id[sp_id] = CastInShot(
                entity_id=sp_id, position="center", framing="MCU", speaking=True
            )
    return deduplicate_cast_positions(cast_by_id, prev_positions)


def _normalize_shot_beats(
    sh: ShotDraft,
    sview: SceneView,
    dur: float,
    cast_ids: list[str],
    valid_char_ids: set[str],
    clean_props: list[str],
) -> list[ActionBeat]:
    """Normalize ActionBeat timing windows and subject IDs across `dur` seconds."""
    raw_beats = sh.beats or [
        ActionBeat(
            t_start_s=0.0,
            t_end_s=dur,
            description=sview.scene.summary or sview.scene.heading,
            subject_ids=cast_ids,
        )
    ]
    step = round(dur / max(1, len(raw_beats)), 2)
    clean_beats: list[ActionBeat] = []
    for b_idx, b in enumerate(raw_beats):
        t0 = round(b_idx * step, 2)
        t1 = round(dur if b_idx == len(raw_beats) - 1 else (b_idx + 1) * step, 2)
        subj = [
            sid for sid in b.subject_ids if sid in valid_char_ids or sid in clean_props
        ] or cast_ids
        desc = re.sub(
            r"tearful\s+starlight\s+sparkles?",
            "subtle glistening tears",
            normalize_indian_epic_names(b.description),
            flags=re.IGNORECASE,
        )
        clean_beats.append(
            ActionBeat(
                t_start_s=t0,
                t_end_s=max(t0 + 0.5, t1),
                description=desc,
                subject_ids=subj,
            )
        )
    return clean_beats


def _persist_director_shot(
    ctx: ToolContext,
    scene_id: str,
    idx: int,
    sh: ShotDraft,
    sview: SceneView,
    lead_id: str,
    valid_char_ids: set[str],
    valid_prop_ids: set[str],
    ev_ids: list[str],
    shot_dlgs: list[str],
    dlg_by_id: dict[str, DialogueLine],
    base_order: int,
    prev_positions: dict[str, str],
) -> None:
    """Validate and persist a single `ShotDraft` into the repository."""
    shot_dlgs, dur = _select_shot_dialogues_and_duration(sh, shot_dlgs, dlg_by_id)
    shot_order = base_order + min(idx - 1, max(0, len(sview.events) - 1))
    cast_by_id = _resolve_shot_cast(
        sh, lead_id, valid_char_ids, shot_dlgs, dlg_by_id, prev_positions
    )
    clean_props = [pid for pid in sh.prop_ids if pid in valid_prop_ids]
    for cid in cast_by_id:
        held = state_at(ctx.repo, cid, shot_order).get("holding")
        if held and held in valid_prop_ids and held not in clean_props:
            clean_props.append(held)
    clean_beats = _normalize_shot_beats(
        sh, sview, dur, list(cast_by_id.keys()), valid_char_ids, clean_props
    )
    wt.put_shot(
        ctx,
        shot_id=f"shot_{scene_id}_{idx:02d}",
        scene_id=scene_id,
        index_in_scene=idx,
        story_order=shot_order,
        duration_s=dur,
        location_id=sview.scene.location_id,
        covers_event_ids=ev_ids,
        cast=list(cast_by_id.values()),
        prop_ids=clean_props,
        camera=sh.camera,
        beats=clean_beats,
        dialogue_ids=shot_dlgs,
        continue_from_last_frame=(idx > 1),
    )


def _build_director_prompt(
    ctx: ToolContext,
    scene_id: str,
    story_context: str,
    sview: SceneView,
    chars: list[Entity],
    props: list[Entity],
    ev_ids: list[str],
) -> str:
    """Build the user prompt for `DIRECTOR` scene shot breakdown."""
    from ...presets import resolve_production_presets

    meta = ctx.repo.get_project_meta()
    bundle = resolve_production_presets(
        visual_style_id=meta.visual_style_preset if meta else None,
        color_palette_id=meta.color_palette_preset if meta else None,
        director_style_id=meta.director_style_preset if meta else None,
    )
    char_list = [{"id": c.id, "name": c.canonical_name} for c in chars]
    prop_list = [{"id": p.id, "name": p.canonical_name} for p in props]
    dlg_list = [
        {"id": d.id, "speaker_id": d.speaker_id, "text": d.text}
        for d in sview.dialogue_lines
    ]
    steps_list = [st.model_dump() for st in sview.scene.interaction_steps]
    return (
        f"Directorial Style Preset ({bundle.director_style.label}): {bundle.director_style.instruction_prompt}\n\n"
        f"Full Story Context:\n{story_context}\n\n"
        f"Break scene '{scene_id}' (location_id='{sview.scene.location_id}') into 2 cinematic Shot nodes.\n"
        f"Algorithmic Screenplay Steps (translate 1-to-1 into shot ActionBeats): {steps_list}\n"
        f"Valid character entity_ids in this scene: {char_list}\n"
        f"Valid prop_ids in this scene: {prop_list}\n"
        f"Valid event_ids to cover: {ev_ids}\n"
        f"Valid dialogue_ids: {dlg_list}\n"
        "CRITICAL RULES:\n"
        "1. Make every ActionBeat description vividly depict the exact story action in this scene's events and algorithmic interaction_steps.\n"
        "2. Only include a prop in `prop_ids` if physically used in that shot.\n"
        "3. Partition `dialogue_ids` across shots in chronological order (1 speaker per shot when possible) and preserve 180-degree screen positions (`left`/`center`/`right`).\n"
        "4. For crying/emotional moments, describe subtle glistening eye moisture — NEVER 'tearful starlight sparkles'.\n\n"
        f"SCENE VIEW:\n{sview.model_dump_json()}"
    )


def _sync_scene_event_orders(
    ctx: ToolContext, sview: SceneView
) -> tuple[int, list[str]]:
    """Normalize `story_order` on `sview.events` and return `(base_order, ev_ids)`."""
    base_order = sview.scene.index * 10
    for e_idx, ev in enumerate(sview.events):
        target_order = base_order + e_idx
        if ev.story_order != target_order:
            ctx.repo.put_event(ev.model_copy(update={"story_order": target_order}))
    return base_order, [e.id for e in sview.events]


def run_director_for_scene(
    ctx: ToolContext,
    scene_id: str,
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run DIRECTOR (`director_agent`) to decompose `scene_id` into camera-blocked Shots."""
    sview = scene_view(ctx.repo, scene_id)
    chars = [
        e for e in sview.entities_in_scene if e.entity_type == EntityType.CHARACTER
    ] or ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    props = [e for e in sview.entities_in_scene if e.entity_type == EntityType.OBJECT]
    if not props and len(ctx.repo.list_scenes()) <= 1:
        props = ctx.repo.list_entities(entity_type=EntityType.OBJECT)

    base_order, ev_ids = _sync_scene_event_orders(ctx, sview)
    dlg_ids = [d.id for d in sview.dialogue_lines]
    dlg_by_id = {d.id: d for d in sview.dialogue_lines}
    lead_id = chars[0].id if chars else "char_arjun"
    story_context = normalize_indian_epic_names(ctx.repo.get_source_text() or "")

    fb_dir = _build_director_fallback(
        scene_id, sview, chars, [p.id for p in props[:1]], ev_ids, dlg_ids, base_order
    )
    res = run_role(
        role=Role.DIRECTOR,
        ctx=ctx,
        user_prompt=_build_director_prompt(
            ctx, scene_id, story_context, sview, chars, props, ev_ids
        ),
        output_schema=DirectorSceneOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: fb_dir,
    )
    valid_char_ids, valid_prop_ids = {c.id for c in chars}, {p.id for p in props}
    shots = list(res.output.shots or fb_dir.shots)
    partitioned_dlgs = partition_scene_dialogues(shots, dlg_ids, dlg_by_id)
    shot_pairs = expand_overbudget_shot_buckets(shots, partitioned_dlgs, dlg_by_id)
    prev_positions: dict[str, str] = {}
    for idx, (sh, sh_dlgs) in enumerate(shot_pairs, start=1):
        _persist_director_shot(
            ctx,
            scene_id,
            idx,
            sh,
            sview,
            lead_id,
            valid_char_ids,
            valid_prop_ids,
            ev_ids,
            sh_dlgs,
            dlg_by_id,
            base_order,
            prev_positions,
        )
    return res
