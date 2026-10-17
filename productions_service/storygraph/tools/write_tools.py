"""Permissioned write tools for StoryGraph role agents, enforcing ROLE_SCOPE and audit logging."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from ..audit import append_audit
from ..errors import NotFound, PermissionDenied
from ..schema import (
    ActionBeat,
    Appearance,
    Asset,
    AttributeVal,
    CameraSpec,
    CastInShot,
    ChangeRequest,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    MusicCue,
    Provenance,
    QAReport,
    Role,
    Scene,
    Shot,
    StateEffect,
    Status,
    StyleGuide,
)
from .registry import (
    ToolContext,
    assert_asset_kind_allowed,
    assert_can_write,
    assert_entity_type_allowed,
)


def put_style_guide(
    ctx: ToolContext,
    visual_medium: str,
    palette: list[str],
    lens_language: str,
    lighting_rules: str,
    aspect_ratio: str = "16:9",
    fps: int = 24,
    avoid: list[str] | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "StyleGuide")
    prev = ctx.repo.get_style_guide()
    sg = StyleGuide(
        id="style_guide",
        created_by=ctx.role,
        status=Status.APPROVED,
        visual_medium=visual_medium,
        palette=palette,
        lens_language=lens_language,
        lighting_rules=lighting_rules,
        aspect_ratio=aspect_ratio
        if aspect_ratio in ("16:9", "9:16", "2.39:1")
        else "16:9",  # type: ignore[arg-type]
        fps=fps,
        avoid=avoid or ["text overlays", "watermarks", "deformed hands", "extra limbs"],
    )
    saved = ctx.repo.put_style_guide(sg)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_style_guide",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Updated StyleGuide ({visual_medium})",
    )
    return saved.model_dump(mode="json")


def put_entity(
    ctx: ToolContext,
    entity_id: str,
    entity_type: str | EntityType,
    canonical_name: str,
    aliases: list[str] | None = None,
    attributes: dict[str, AttributeVal | dict[str, Any] | str] | None = None,
    voice_profile_id: str | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Entity")
    et = EntityType(entity_type)
    assert_entity_type_allowed(ctx.role, et)
    prev = ctx.repo.get_entity(entity_id)

    parsed_attrs: dict[str, AttributeVal] = dict(prev.attributes) if prev else {}
    for k, v in (attributes or {}).items():
        if isinstance(v, AttributeVal):
            parsed_attrs[k] = v
        elif isinstance(v, dict):
            parsed_attrs[k] = AttributeVal.model_validate(v)
        else:
            parsed_attrs[k] = AttributeVal(
                value=str(v), provenance=Provenance.FROM_TEXT
            )

    ent = Entity(
        id=entity_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        entity_type=et,
        canonical_name=canonical_name,
        aliases=aliases if aliases is not None else (prev.aliases if prev else []),
        attributes=parsed_attrs,
        voice_profile_id=voice_profile_id or (prev.voice_profile_id if prev else None),
    )
    saved = ctx.repo.put_entity(ent)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_entity",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Put {et} entity '{canonical_name}'",
    )
    return saved.model_dump(mode="json")


def propose_entity_merge(
    ctx: ToolContext,
    keep_id: str,
    drop_id: str,
    reason: str = "Duplicate alias",
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Entity")
    keep = ctx.repo.get_entity(keep_id)
    drop = ctx.repo.get_entity(drop_id)
    if not keep or not drop:
        raise NotFound(f"Cannot merge '{drop_id}' into '{keep_id}': entity missing")
    merged_aliases = list(
        dict.fromkeys([*keep.aliases, drop.canonical_name, *drop.aliases])
    )
    merged_attrs = {**drop.attributes, **keep.attributes}
    updated = keep.model_copy(
        update={"aliases": merged_aliases, "attributes": merged_attrs}
    )
    saved = ctx.repo.put_entity(updated)
    ctx.repo.store.delete("entities", drop_id)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "propose_entity_merge",
        saved.id,
        keep.version,
        saved.version,
        f"Merged '{drop_id}' into '{keep_id}' ({reason})",
    )
    return saved.model_dump(mode="json")


def put_event(
    ctx: ToolContext,
    event_id: str,
    story_order: int,
    scene_id: str,
    summary: str,
    participants: list[str],
    effects: list[StateEffect | dict[str, Any]] | None = None,
    source_span: tuple[int, int] = (0, 0),
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Event")
    prev = ctx.repo.get_event(event_id)
    parsed_effects = [
        e if isinstance(e, StateEffect) else StateEffect.model_validate(e)
        for e in (effects or [])
    ]
    ev = Event(
        id=event_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        story_order=story_order,
        scene_id=scene_id,
        summary=summary,
        participants=participants,
        effects=parsed_effects,
        source_span=source_span,
    )
    saved = ctx.repo.put_event(ev)
    scene = ctx.repo.get_scene(scene_id)
    if scene and saved.id not in scene.event_ids:
        ctx.repo.put_scene(
            scene.model_copy(update={"event_ids": [*scene.event_ids, saved.id]})
        )
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_event",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Put event #{story_order} in {scene_id}",
    )
    return saved.model_dump(mode="json")


def put_scene(
    ctx: ToolContext,
    scene_id: str,
    index: int,
    heading: str,
    location_id: str,
    time_of_day: str,
    weather: str = "clear",
    event_ids: list[str] | None = None,
    shot_ids: list[str] | None = None,
    summary: str = "",
    mood: str = "",
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Scene")
    prev = ctx.repo.get_scene(scene_id)
    scene = Scene(
        id=scene_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        index=index,
        heading=heading,
        location_id=location_id,
        time_of_day=time_of_day,
        weather=weather,
        event_ids=event_ids
        if event_ids is not None
        else (prev.event_ids if prev else []),
        shot_ids=shot_ids if shot_ids is not None else (prev.shot_ids if prev else []),
        summary=summary or (prev.summary if prev else ""),
        mood=mood or (prev.mood if prev else ""),
    )
    saved = ctx.repo.put_scene(scene)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_scene",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Put scene {index}: {heading}",
    )
    return saved.model_dump(mode="json")


def update_scene_script(
    ctx: ToolContext,
    scene_id: str,
    summary: str,
    mood: str,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Scene")
    prev = ctx.repo.get_scene(scene_id)
    if not prev:
        raise NotFound(f"Scene {scene_id} not found")
    updated = prev.model_copy(update={"summary": summary, "mood": mood})
    saved = ctx.repo.put_scene(updated)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "update_scene_script",
        saved.id,
        prev.version,
        saved.version,
        f"Updated screenplay summary & mood for {scene_id}",
    )
    return saved.model_dump(mode="json")


def put_dialogue(
    ctx: ToolContext,
    line_id: str,
    scene_id: str,
    order_in_scene: int,
    speaker_id: str,
    text: str,
    delivery: str = "natural",
    addressee_id: str | None = None,
    shot_id: str | None = None,
    language: str = "en",
) -> dict[str, Any]:
    assert_can_write(ctx.role, "DialogueLine")
    prev = ctx.repo.get_dialogue(line_id)
    line = DialogueLine(
        id=line_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        scene_id=scene_id,
        shot_id=shot_id,
        order_in_scene=order_in_scene,
        speaker_id=speaker_id,
        addressee_id=addressee_id,
        text=text,
        delivery=delivery,
        language=language,
    )
    saved = ctx.repo.put_dialogue(line)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_dialogue",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Dialogue line #{order_in_scene} by {speaker_id} in {scene_id}",
    )
    return saved.model_dump(mode="json")


def set_entity_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str | AttributeVal | dict[str, Any]],
    provenance: str | Provenance = Provenance.INVENTED,
) -> dict[str, Any]:
    """Set visual/physical attributes on an Entity, enforcing entity-type isolation and preserving FROM_TEXT attributes."""
    if ctx.role not in (Role.SCRIPT_SUPERVISOR, Role.PIPELINE, Role.HUMAN):
        assert_can_write(ctx.role, "Entity.attributes")
    ent = ctx.repo.get_entity(entity_id)
    if not ent:
        raise NotFound(f"Entity {entity_id} not found")
    assert_entity_type_allowed(ctx.role, ent.entity_type)

    prov_enum = Provenance(provenance)
    merged_attrs = dict(ent.attributes)
    for k, raw_val in attributes.items():
        existing_attr = merged_attrs.get(k)
        # Designers cannot overwrite FROM_TEXT provenance attributes
        if (
            existing_attr
            and existing_attr.provenance == Provenance.FROM_TEXT
            and ctx.role
            in (
                Role.CHARACTER_DESIGNER,
                Role.LOCATION_DESIGNER,
                Role.OBJECT_DESIGNER,
                Role.DESIGNER,
            )
        ):
            raise PermissionDenied(
                f"Role '{ctx.role}' cannot overwrite FROM_TEXT attribute '{k}' on '{entity_id}'"
            )
        if isinstance(raw_val, AttributeVal):
            attr_obj = raw_val
        elif isinstance(raw_val, dict):
            attr_obj = AttributeVal.model_validate(raw_val)
        else:
            attr_obj = AttributeVal(value=str(raw_val), provenance=prov_enum)

        if attr_obj.provenance == Provenance.FROM_TEXT and ctx.role in (
            Role.CHARACTER_DESIGNER,
            Role.LOCATION_DESIGNER,
            Role.OBJECT_DESIGNER,
            Role.DESIGNER,
        ):
            raise PermissionDenied(
                f"Role '{ctx.role}' can only write 'inferred' or 'invented' provenance, not 'from_text'"
            )
        merged_attrs[k] = attr_obj

    updated = ent.model_copy(update={"attributes": merged_attrs})
    saved = ctx.repo.put_entity(updated)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "set_entity_attributes",
        saved.id,
        ent.version,
        saved.version,
        f"Set {len(attributes)} attribute(s) on {ent.entity_type} '{entity_id}'",
    )
    return saved.model_dump(mode="json")


def set_character_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str],
    provenance: str = "invented",
) -> dict[str, Any]:
    ent = ctx.repo.get_entity(entity_id)
    if not ent or ent.entity_type != EntityType.CHARACTER:
        raise PermissionDenied(
            f"Entity '{entity_id}' is not a character (found: {ent.entity_type if ent else None})"
        )
    return set_entity_attributes(ctx, entity_id, attributes, provenance=provenance)


def set_location_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str],
    provenance: str = "invented",
) -> dict[str, Any]:
    ent = ctx.repo.get_entity(entity_id)
    if not ent or ent.entity_type != EntityType.LOCATION:
        raise PermissionDenied(
            f"Entity '{entity_id}' is not a location (found: {ent.entity_type if ent else None})"
        )
    return set_entity_attributes(ctx, entity_id, attributes, provenance=provenance)


def set_object_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str],
    provenance: str = "invented",
) -> dict[str, Any]:
    ent = ctx.repo.get_entity(entity_id)
    if not ent or ent.entity_type != EntityType.OBJECT:
        raise PermissionDenied(
            f"Entity '{entity_id}' is not an object (found: {ent.entity_type if ent else None})"
        )
    return set_entity_attributes(ctx, entity_id, attributes, provenance=provenance)


def add_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    wardrobe: str | None = None,
    condition_tags: list[str] | None = None,
    status: Status = Status.PROPOSED,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Appearance")
    ent = ctx.repo.get_entity(entity_id)
    if not ent:
        raise NotFound(f"Entity '{entity_id}' not found")
    assert_entity_type_allowed(ctx.role, ent.entity_type)

    app = Appearance(
        id=f"app_{entity_id}_{state_label}",
        created_by=ctx.role,
        status=status,
        entity_id=entity_id,
        state_label=state_label,
        visual_description=visual_description,
        wardrobe=wardrobe,
        condition_tags=condition_tags or [],
    )
    saved = ctx.repo.add_appearance(app)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "add_appearance",
        saved.id,
        (saved.version - 1) if saved.version > 1 else None,
        saved.version,
        f"Added appearance '{saved.id}' for {ent.entity_type} '{entity_id}'",
    )
    return saved.model_dump(mode="json")


def add_character_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    wardrobe: str | None = None,
    condition_tags: list[str] | None = None,
) -> dict[str, Any]:
    ent = ctx.repo.get_entity(entity_id)
    if not ent or ent.entity_type != EntityType.CHARACTER:
        raise PermissionDenied(f"Entity '{entity_id}' is not a character")
    return add_appearance(
        ctx, entity_id, state_label, visual_description, wardrobe, condition_tags
    )


def add_location_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    condition_tags: list[str] | None = None,
) -> dict[str, Any]:
    ent = ctx.repo.get_entity(entity_id)
    if not ent or ent.entity_type != EntityType.LOCATION:
        raise PermissionDenied(f"Entity '{entity_id}' is not a location")
    return add_appearance(
        ctx, entity_id, state_label, visual_description, None, condition_tags
    )


def add_object_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    condition_tags: list[str] | None = None,
) -> dict[str, Any]:
    ent = ctx.repo.get_entity(entity_id)
    if not ent or ent.entity_type != EntityType.OBJECT:
        raise PermissionDenied(f"Entity '{entity_id}' is not an object")
    return add_appearance(
        ctx, entity_id, state_label, visual_description, None, condition_tags
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
    append_audit(
        ctx.repo.store,
        ctx.role,
        "register_asset",
        saved.id,
        (saved.version - 1) if saved.version > 1 else None,
        saved.version,
        f"Registered {kind} asset '{saved.id}'",
    )
    return saved.model_dump(mode="json")


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
    style_prefix = (
        f"{sg.visual_medium}. Palette: {', '.join(sg.palette)}. {sg.lighting_rules}."
        if sg
        else "Cinematic still frame."
    )
    if kind == "character_sheet":
        framing_hint = "Character reference turnaround sheet, neutral studio rim-lit portrait + full-body standing pose"
    elif kind == "location_plate":
        framing_hint = "Establishing wide architectural/environmental plate, unoccupied set reference"
    else:
        framing_hint = "Hero prop reference sheet, studio macro close-up showing texture, geometry, and scale"

    full_prompt = (
        f"{style_prefix} {framing_hint} of {ent.canonical_name}: "
        f"{app.visual_description}"
        f"{f', wearing {app.wardrobe}' if app.wardrobe else ''}. {extra_prompt}".strip()
    )
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
        music_cue_id=music_cue_id
        if music_cue_id is not None
        else (prev.music_cue_id if prev else None),
        sfx=sfx if sfx is not None else (prev.sfx if prev else []),
        continue_from_last_frame=continue_from_last_frame,
        stale=False,
        stale_reason=None,
    )
    saved = ctx.repo.put_shot(shot)
    # Link dialogue_ids back to shot_id
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
