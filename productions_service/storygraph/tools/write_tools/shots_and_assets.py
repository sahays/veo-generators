"""Permissioned asset generation, shot, audio, critique, and change-request write tools."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from ...audit import append_audit
from ...errors import NotFound
from ...schema import (
    ActionBeat,
    Appearance,
    Asset,
    CameraSpec,
    CastInShot,
    ChangeRequest,
    Entity,
    MusicCue,
    QAReport,
    Role,
    Shot,
    Status,
    StyleGuide,
)
from ..registry import (
    ToolContext,
    assert_asset_kind_allowed,
    assert_can_write,
    assert_entity_type_allowed,
)


def register_asset(
    ctx: ToolContext,
    base_asset_id: str,
    kind: str,
    png_bytes: bytes,
    depicts_entity_ids: list[str],
    appearance_ids: list[str],
    generation_prompt: str,
    model: str,
    seed: int | None = None,
    status: Status = Status.PROPOSED,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Asset")
    assert_asset_kind_allowed(ctx.role, kind)
    for eid in depicts_entity_ids:
        ent = ctx.repo.get_entity(eid)
        if ent:
            assert_entity_type_allowed(ctx.role, ent.entity_type)

    sha = hashlib.sha256(png_bytes).hexdigest()
    uri = ctx.repo.blobs.put_bytes(
        f"assets/{base_asset_id}_{sha[:8]}.png", png_bytes, content_type="image/png"
    )
    asset = Asset(
        id=base_asset_id,
        created_by=ctx.role,
        status=status,
        kind=kind,  # type: ignore[arg-type]
        uri=uri,
        sha256=sha,
        depicts_entity_ids=depicts_entity_ids,
        appearance_ids=appearance_ids,
        generation_prompt=generation_prompt,
        seed=seed,
        model=model,
    )
    saved = ctx.repo.add_asset(asset)
    prev_ver = (saved.version - 1) if saved.version > 1 else None
    append_audit(
        ctx.repo.store,
        ctx.role,
        "register_asset",
        saved.id,
        prev_ver,
        saved.version,
        f"Registered {kind} asset '{saved.id}'",
    )
    return saved.model_dump(mode="json")


def _build_asset_generation_prompt(
    sg: StyleGuide | None, ent: Entity, app: Appearance, kind: str, extra_prompt: str
) -> str:
    style_prefix = (
        f"{sg.visual_medium}. Palette: {', '.join(sg.palette)}. {sg.lighting_rules}."
        if sg
        else "Cinematic still frame."
    )
    hints = {
        "character_sheet": "Single full-body front-facing character reference portrait on neutral studio backdrop (ONE figure only, NO turnaround, NO multiple poses, NO split panels, empty hands)",
        "location_plate": "Establishing wide architectural/environmental plate, unoccupied set reference",
    }
    framing_hint = hints.get(
        kind,
        "Hero prop reference sheet, studio macro close-up showing texture, geometry, and scale",
    )
    wardrobe_suffix = f", wearing {app.wardrobe}" if app.wardrobe else ""
    return f"{style_prefix} {framing_hint} of {ent.canonical_name}: {app.visual_description}{wardrobe_suffix}. {extra_prompt}".strip()


def _generate_entity_asset_with_adapter(
    ctx: ToolContext,
    entity_id: str,
    appearance_id: str,
    kind: str,
    extra_prompt: str = "",
    seed: int = 42,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Asset")
    assert_asset_kind_allowed(ctx.role, kind)
    ent = ctx.repo.get_entity(entity_id)
    if not ent:
        raise NotFound(f"Entity {entity_id} not found")
    assert_entity_type_allowed(ctx.role, ent.entity_type)
    app = ctx.repo.get_appearance(appearance_id)
    if not app:
        raise NotFound(f"Appearance {appearance_id} not found")
    sg = ctx.repo.get_style_guide()
    full_prompt = _build_asset_generation_prompt(sg, ent, app, kind, extra_prompt)
    if ctx.image_gen is not None:
        png_bytes = ctx.image_gen.generate(
            prompt=full_prompt,
            reference_images=None,
            aspect_ratio=sg.aspect_ratio if sg else "16:9",
            seed=seed,
        )
    else:
        png_bytes = b"\x89PNG\r\n\x1a\n" + hashlib.sha256(full_prompt.encode()).digest()

    return register_asset(
        ctx=ctx,
        base_asset_id=f"ast_{entity_id}_{app.state_label}",
        kind=kind,
        png_bytes=png_bytes,
        depicts_entity_ids=[entity_id],
        appearance_ids=[appearance_id],
        generation_prompt=full_prompt,
        model=ctx.cfg.image.model,
        seed=seed,
    )


def generate_character_asset(
    ctx: ToolContext,
    entity_id: str,
    appearance_id: str,
    extra_prompt: str = "",
    seed: int = 42,
) -> dict[str, Any]:
    return _generate_entity_asset_with_adapter(
        ctx, entity_id, appearance_id, "character_sheet", extra_prompt, seed
    )


def generate_location_asset(
    ctx: ToolContext,
    entity_id: str,
    appearance_id: str,
    extra_prompt: str = "",
    seed: int = 42,
) -> dict[str, Any]:
    return _generate_entity_asset_with_adapter(
        ctx, entity_id, appearance_id, "location_plate", extra_prompt, seed
    )


def generate_object_asset(
    ctx: ToolContext,
    entity_id: str,
    appearance_id: str,
    extra_prompt: str = "",
    seed: int = 42,
) -> dict[str, Any]:
    return _generate_entity_asset_with_adapter(
        ctx, entity_id, appearance_id, "prop_sheet", extra_prompt, seed
    )


def _parse_shot_inputs(
    cast: list[CastInShot | dict[str, Any]] | None,
    camera: CameraSpec | dict[str, Any] | None,
    beats: list[ActionBeat | dict[str, Any]] | None,
) -> tuple[list[CastInShot], CameraSpec, list[ActionBeat]]:
    parsed_cast = [
        c if isinstance(c, CastInShot) else CastInShot.model_validate(c)
        for c in (cast or [])
    ]
    parsed_cam = (
        camera
        if isinstance(camera, CameraSpec)
        else (CameraSpec.model_validate(camera) if camera else CameraSpec())
    )
    parsed_beats = [
        b if isinstance(b, ActionBeat) else ActionBeat.model_validate(b)
        for b in (beats or [])
    ]
    return parsed_cast, parsed_cam, parsed_beats


def put_shot(
    ctx: ToolContext,
    shot_id: str,
    scene_id: str,
    index_in_scene: int,
    story_order: int,
    duration_s: float,
    location_id: str,
    covers_event_ids: list[str] | None = None,
    cast: list[CastInShot | dict[str, Any]] | None = None,
    prop_ids: list[str] | None = None,
    camera: CameraSpec | dict[str, Any] | None = None,
    beats: list[ActionBeat | dict[str, Any]] | None = None,
    dialogue_ids: list[str] | None = None,
    continue_from_last_frame: bool = False,
    music_cue_id: str | None = None,
    sfx: list[str] | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Shot")
    prev = ctx.repo.get_shot(shot_id)
    parsed_cast, parsed_cam, parsed_beats = _parse_shot_inputs(cast, camera, beats)
    resolved_cue = (
        music_cue_id
        if music_cue_id is not None
        else (prev.music_cue_id if prev else None)
    )
    resolved_sfx = sfx if sfx is not None else (prev.sfx if prev else [])
    shot = Shot(
        id=shot_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        scene_id=scene_id,
        index_in_scene=index_in_scene,
        story_order=story_order,
        covers_event_ids=covers_event_ids or [],
        duration_s=duration_s,
        location_id=location_id,
        cast=parsed_cast,
        prop_ids=prop_ids or [],
        camera=parsed_cam,
        beats=parsed_beats,
        dialogue_ids=dialogue_ids or [],
        music_cue_id=resolved_cue,
        sfx=resolved_sfx,
        continue_from_last_frame=continue_from_last_frame,
        stale=False,
        stale_reason=None,
    )
    saved = ctx.repo.put_shot(shot)
    for did in saved.dialogue_ids:
        dline = ctx.repo.get_dialogue(did)
        if dline and dline.shot_id != saved.id:
            ctx.repo.put_dialogue(dline.model_copy(update={"shot_id": saved.id}))

    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_shot",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Put shot {saved.id} (order {story_order}, {duration_s}s)",
    )
    return saved.model_dump(mode="json")


def put_music_cue(
    ctx: ToolContext,
    cue_id: str,
    scene_id: str,
    mood: str,
    instrumentation: str,
    tempo_bpm: int,
    motif_tags: list[str] | None = None,
    audio_asset_id: str | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "MusicCue")
    prev = ctx.repo.get_music_cue(cue_id)
    cue = MusicCue(
        id=cue_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        scene_id=scene_id,
        mood=mood,
        instrumentation=instrumentation,
        tempo_bpm=tempo_bpm,
        motif_tags=motif_tags or [],
        audio_asset_id=audio_asset_id,
    )
    saved = ctx.repo.put_music_cue(cue)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_music_cue",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Music cue '{saved.id}' ({mood}, {tempo_bpm}bpm)",
    )
    return saved.model_dump(mode="json")


def set_shot_audio(
    ctx: ToolContext,
    shot_id: str,
    music_cue_id: str | None,
    sfx: list[str],
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Shot.music_cue_id")
    assert_can_write(ctx.role, "Shot.sfx")
    prev = ctx.repo.get_shot(shot_id)
    if not prev:
        raise NotFound(f"Shot {shot_id} not found")
    updated = prev.model_copy(update={"music_cue_id": music_cue_id, "sfx": sfx})
    saved = ctx.repo.put_shot(updated)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "set_shot_audio",
        saved.id,
        prev.version,
        saved.version,
        f"Set audio on shot '{shot_id}' (cue={music_cue_id}, sfx={len(sfx)})",
    )
    return saved.model_dump(mode="json")


def record_asset_critique(
    ctx: ToolContext,
    asset_id: str,
    approved: bool,
    qa_notes: str,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Asset.qa_notes")
    prev = ctx.repo.get_asset(asset_id)
    if not prev:
        raise NotFound(f"Asset {asset_id} not found")
    new_status = Status.APPROVED if approved else Status.PROPOSED
    saved = ctx.repo.update_asset(asset_id, status=new_status, qa_notes=qa_notes)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "record_asset_critique",
        saved.id,
        prev.version,
        saved.version,
        f"Critic asset review: approved={approved}",
    )
    return saved.model_dump(mode="json")


def record_clip_qa(
    ctx: ToolContext,
    run_id: str,
    qa_report: QAReport | dict[str, Any],
    extracted_last_frame_asset_id: str | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "GenerationRun.qa_scores")
    assert_can_write(ctx.role, "GenerationRun.status")
    report = (
        qa_report
        if isinstance(qa_report, QAReport)
        else QAReport.model_validate(qa_report)
    )
    status = Status.APPROVED if report.passed else Status.FAILED
    saved = ctx.repo.update_generation_run_qa(
        run_id=run_id,
        qa_scores=report,
        status=status,
        extracted_last_frame_asset_id=extracted_last_frame_asset_id,
    )
    append_audit(
        ctx.repo.store,
        ctx.role,
        "record_clip_qa",
        saved.id,
        saved.version - 1,
        saved.version,
        f"Clip QA on {run_id}: passed={report.passed}",
    )
    return saved.model_dump(mode="json")


def create_change_request(
    ctx: ToolContext,
    to_role: str | Role,
    target_node_id: str,
    reason: str,
    proposed_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "ChangeRequest")
    cr = ChangeRequest(
        id=f"cr_{uuid.uuid4().hex[:10]}",
        created_by=ctx.role,
        status=Status.PROPOSED,
        from_role=ctx.role,
        to_role=Role(to_role),
        target_node_id=target_node_id,
        reason=reason,
        proposed_patch=proposed_patch or {},
    )
    saved = ctx.repo.add_change_request(cr)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "create_change_request",
        saved.id,
        None,
        saved.version,
        f"ChangeRequest {ctx.role} -> {to_role} on {target_node_id}",
    )
    return saved.model_dump(mode="json")
