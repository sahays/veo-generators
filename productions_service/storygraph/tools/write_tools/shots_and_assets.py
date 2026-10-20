"""Permissioned asset generation and shot write tools."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from ...audit import append_audit
from ...errors import NotFound
from ...schema import (
    ActionBeat,
    Appearance,
    Asset,
    CameraSpec,
    CastInShot,
    Entity,
    Shot,
    ShotLook,
    Status,
    StyleGuide,
)
from ...shots import (
    compute_shot_content_hash,
    find_scene_clip,
    mark_stale_and_reset,
)
from ..registry import (
    ToolContext,
    assert_asset_kind_allowed,
    assert_can_write,
    assert_entity_type_allowed,
)
from .audio_and_qa import (
    create_change_request,
    put_music_cue,
    record_asset_critique,
    record_clip_qa,
    set_shot_audio,
)

logger = logging.getLogger(__name__)


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


def _stamp_content_hash(ctx: ToolContext, prev: Shot | None, shot: Shot) -> Shot:
    """Fingerprint `shot`; mark it stale when its render content differs from `prev`.

    Unchanged content keeps the previous staleness verdict, so a no-op regeneration
    neither invalidates approved clips nor clears an upstream-asset staleness flag.
    """
    scene = ctx.repo.get_scene(shot.scene_id)
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
    reason = f"Shot content changed by {ctx.role} regeneration"
    logger.info(
        "Shot content changed; existing clips invalidated",
        extra={
            "who": str(ctx.role),
            "where": "write_tools.shots_and_assets._stamp_content_hash",
            "what": "shot_marked_stale",
            "when": datetime.now(UTC).isoformat(),
            "why": reason,
            "how": "sha256 render-content fingerprint mismatch",
            "project_id": ctx.repo.project_id,
            "shot_id": shot.id,
            "prev_hash": prev.content_hash,
            "new_hash": new_hash,
        },
    )
    hashed = shot.model_copy(update={"content_hash": new_hash})
    return mark_stale_and_reset(hashed, reason)


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
    foley_sfx: list[str] | None = None,
    environmental_sfx: list[str] | None = None,
    action_focus_sfx: list[str] | None = None,
    entry_motion_vector: str | None = None,
    exit_motion_vector: str | None = None,
    look: ShotLook | dict[str, Any] | None = None,
    clip_index: int | None = None,
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
    parsed_look = (
        (look if isinstance(look, ShotLook) else ShotLook.model_validate(look))
        if look is not None
        else (prev.look if prev else None)
    )
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
        look=parsed_look,
        clip_index=clip_index,
        beats=parsed_beats,
        dialogue_ids=dialogue_ids or [],
        music_cue_id=resolved_cue,
        sfx=resolved_sfx,
        foley_sfx=foley_sfx
        if foley_sfx is not None
        else (prev.foley_sfx if prev else []),
        environmental_sfx=(
            environmental_sfx
            if environmental_sfx is not None
            else (prev.environmental_sfx if prev else [])
        ),
        action_focus_sfx=(
            action_focus_sfx
            if action_focus_sfx is not None
            else (prev.action_focus_sfx if prev else [])
        ),
        entry_motion_vector=entry_motion_vector
        or (prev.entry_motion_vector if prev else "stationary"),
        exit_motion_vector=exit_motion_vector
        or (prev.exit_motion_vector if prev else "stationary"),
        continue_from_last_frame=continue_from_last_frame,
        stale=False,
        stale_reason=None,
    )
    saved = ctx.repo.put_shot(_stamp_content_hash(ctx, prev, shot))
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


__all__ = [
    "_generate_entity_asset_with_adapter",
    "create_change_request",
    "generate_character_asset",
    "generate_location_asset",
    "generate_object_asset",
    "put_music_cue",
    "put_shot",
    "record_asset_critique",
    "record_clip_qa",
    "register_asset",
    "set_shot_audio",
]
