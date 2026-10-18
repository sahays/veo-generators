"""Permissioned StyleGuide, Scene, Event, and DialogueLine write tools."""

from __future__ import annotations

from typing import Any

from ...audit import append_audit
from ...errors import NotFound
from ...schema import (
    DialogueLine,
    Event,
    InteractionStep,
    Scene,
    StateEffect,
    Status,
    StyleGuide,
)
from ..registry import ToolContext, assert_can_write


def put_style_guide(
    ctx: ToolContext,
    visual_medium: str,
    palette: list[str],
    lens_language: str,
    lighting_rules: str,
    aspect_ratio: str = "16:9",
    fps: int = 24,
    avoid: list[str] | None = None,
    visual_style_preset: str | None = None,
    color_palette_preset: str | None = None,
    director_style_preset: str | None = None,
    screenplay_style_preset: str | None = None,
    music_style_preset: str | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "StyleGuide")
    prev = ctx.repo.get_style_guide()
    ar = aspect_ratio if aspect_ratio in ("16:9", "9:16", "2.39:1") else "16:9"
    sg = StyleGuide(
        id="style_guide",
        created_by=ctx.role,
        status=Status.APPROVED,
        visual_medium=visual_medium,
        palette=palette,
        lens_language=lens_language,
        lighting_rules=lighting_rules,
        aspect_ratio=ar,  # type: ignore[arg-type]
        fps=fps,
        avoid=avoid or ["text overlays", "watermarks", "deformed hands", "extra limbs"],
        visual_style_preset=visual_style_preset
        or (prev.visual_style_preset if prev else "pixar_3d"),
        color_palette_preset=color_palette_preset
        or (prev.color_palette_preset if prev else "warm_golden_amber"),
        director_style_preset=director_style_preset
        or (prev.director_style_preset if prev else "wonder_spectacle"),
        screenplay_style_preset=screenplay_style_preset
        or (prev.screenplay_style_preset if prev else "algorithmic_wonder"),
        music_style_preset=music_style_preset
        or (prev.music_style_preset if prev else "symphonic_leitmotif"),
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
    interaction_steps: list[InteractionStep | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Scene")
    prev = ctx.repo.get_scene(scene_id)
    ev_ids = event_ids if event_ids is not None else (prev.event_ids if prev else [])
    sh_ids = shot_ids if shot_ids is not None else (prev.shot_ids if prev else [])
    parsed_steps = (
        [
            s if isinstance(s, InteractionStep) else InteractionStep.model_validate(s)
            for s in interaction_steps
        ]
        if interaction_steps is not None
        else (prev.interaction_steps if prev else [])
    )
    scene = Scene(
        id=scene_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        index=index,
        heading=heading,
        location_id=location_id,
        time_of_day=time_of_day,
        weather=weather,
        event_ids=ev_ids,
        shot_ids=sh_ids,
        summary=summary or (prev.summary if prev else ""),
        mood=mood or (prev.mood if prev else ""),
        interaction_steps=parsed_steps,
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
    interaction_steps: list[InteractionStep | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Scene")
    prev = ctx.repo.get_scene(scene_id)
    if not prev:
        raise NotFound(f"Scene {scene_id} not found")
    updates: dict[str, Any] = {"summary": summary, "mood": mood}
    if interaction_steps is not None:
        updates["interaction_steps"] = [
            s if isinstance(s, InteractionStep) else InteractionStep.model_validate(s)
            for s in interaction_steps
        ]
    saved = ctx.repo.put_scene(prev.model_copy(update=updates))
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
