"""Director-owned per-shot cinematography look: preset-constrained defaults, merging, and prompt rules."""

from __future__ import annotations

from typing import Final

from ...clips.models import ColorGradeSpec, LightingSpec
from ...presets import resolve_production_presets
from ...presets.models import ResolvedProductionPresets
from ...repo import Repo
from ...schema import Scene, ShotLook, StyleGuide

_COMPOSITIONS: Final[tuple[str, ...]] = (
    "rule-of-thirds staging with clear foreground, midground and background depth layers",
    "subject-weighted asymmetric frame with a soft foreground occluder for depth",
    "centered, balanced frame with leading lines converging on the subject",
)
_NIGHT_WORDS: Final[tuple[str, ...]] = ("night", "dusk", "evening", "midnight")


def resolve_bundle(repo: Repo) -> ResolvedProductionPresets:
    """Resolve the project's production presets (visual, palette, director, screenplay, music)."""
    meta = repo.get_project_meta()
    return resolve_production_presets(
        visual_style_id=meta.visual_style_preset if meta else None,
        color_palette_id=meta.color_palette_preset if meta else None,
        director_style_id=meta.director_style_preset if meta else None,
        screenplay_style_id=meta.screenplay_style_preset if meta else None,
        music_style_id=meta.music_style_preset if meta else None,
    )


def _default_lighting(sg: StyleGuide | None, scene: Scene) -> LightingSpec:
    is_night = any(w in scene.time_of_day.lower() for w in _NIGHT_WORDS)
    return LightingSpec(
        key=(sg.lighting_rules if sg else "motivated natural key light"),
        fill="soft low-ratio bounce fill preserving facial detail",
        practicals="warm practical lamps visible in frame"
        if is_night
        else "daylight through windows",
        direction="motivated from the dominant practical/window side, consistent across the scene",
        quality="soft, diffused"
        if not is_night
        else "pooled, high-contrast with soft falloff",
    )


def default_look(
    sg: StyleGuide | None,
    bundle: ResolvedProductionPresets,
    scene: Scene,
    position: int,
) -> ShotLook:
    """Deterministic preset-constrained look for shot `position` (1-based) of `scene`."""
    palette = list(sg.palette if sg and sg.palette else bundle.combined_palette)
    return ShotLook(
        lighting=_default_lighting(sg, scene),
        color_grade=ColorGradeSpec(
            shades=palette[:3],
            contrast="medium",
            saturation="natural",
            temperature=bundle.color_palette.lighting_tint,
        ),
        mood=scene.mood or "cinematic",
        composition=_COMPOSITIONS[(position - 1) % len(_COMPOSITIONS)],
        camera_motion_intent=(
            f"{bundle.director_style.preferred_movement.replace('_', ' ')} to "
            f"{'establish the space' if position == 1 else 'follow the action'}"
        ),
    )


def _merge_lighting(
    draft: LightingSpec, anchor: LightingSpec | None, fallback: LightingSpec
) -> LightingSpec:
    """Field-wise: director value, else scene anchor (continuity), else preset default."""
    base = anchor or fallback
    return LightingSpec(
        key=draft.key or base.key or fallback.key,
        fill=draft.fill or base.fill or fallback.fill,
        practicals=draft.practicals or base.practicals or fallback.practicals,
        direction=draft.direction or base.direction or fallback.direction,
        quality=draft.quality or base.quality or fallback.quality,
    )


def merge_look(
    draft: ShotLook | None, scene_anchor: LightingSpec | None, fallback: ShotLook
) -> ShotLook:
    """Merge the director's look with scene lighting continuity and the preset fallback."""
    d = draft or ShotLook()
    cg = d.color_grade
    fb_cg = fallback.color_grade
    return ShotLook(
        lighting=_merge_lighting(d.lighting, scene_anchor, fallback.lighting),
        color_grade=ColorGradeSpec(
            shades=cg.shades or fb_cg.shades,
            contrast=cg.contrast or fb_cg.contrast,
            saturation=cg.saturation or fb_cg.saturation,
            temperature=cg.temperature or fb_cg.temperature,
        ),
        mood=d.mood or fallback.mood,
        composition=d.composition or fallback.composition,
        camera_motion_intent=d.camera_motion_intent or fallback.camera_motion_intent,
    )


def look_constraints_block(
    sg: StyleGuide | None, bundle: ResolvedProductionPresets
) -> str:
    """Prompt block constraining the director's per-shot `look` to the StyleGuide and presets."""
    palette = ", ".join(sg.palette if sg and sg.palette else bundle.combined_palette)
    lighting = sg.lighting_rules if sg else bundle.combined_lighting_rules
    return (
        f"LOOK CONSTRAINTS — StyleGuide medium: {sg.visual_medium if sg else bundle.visual_style.visual_medium}; "
        f"palette: {palette}; lighting rules: {lighting}; colour tint: {bundle.color_palette.lighting_tint}; "
        f"director preset ({bundle.director_style.label}): {bundle.director_style.prompt_directive} "
        f"(preferred lens {bundle.director_style.preferred_lens_mm}mm, movement {bundle.director_style.preferred_movement}).\n"
        "Author a `look` for EVERY shot: `lighting` (key, fill, practicals, direction, quality), "
        "`color_grade` (shades drawn from the palette, contrast, saturation, temperature), `mood`, "
        "`composition` (thirds, depth layers, leading lines) and `camera_motion_intent` (why the camera moves). "
        "Vary composition, grade accents and mood per shot to serve the beat, but keep the lighting "
        "setup (key source, direction, practicals) continuous within a scene.\n"
    )
