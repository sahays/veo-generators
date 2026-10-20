"""Compiler context for Omni clips: clip lookup and LIGHTING / COLOR GRADE / MOOD / COMPOSITION lines."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ValidationFailed
from ..schema import Scene, Shot, StyleGuide
from .models import ClipScript, ColorGradeSpec, LightingSpec, ShotLook
from .validation import CODE_SHOT_MISSING, ClipIssue


@dataclass(frozen=True)
class LookLines:
    """Rendered look lines for the prompt template (StyleGuide fallback when the shot has no look)."""

    lighting: str
    color_grade: str
    mood: str
    composition: str
    camera_motion_intent: str


def resolve_shot_clip(scene: Scene, shot: Shot) -> ClipScript:
    """Return the clip a shot renders; there is no timestamped-beat fallback (S2/S4 must be re-run)."""
    clip = next((c for c in scene.clips if c.clip_index == shot.clip_index), None)
    if clip is None:
        msg = f"Shot '{shot.id}' has no Omni clip (clip_index={shot.clip_index}); re-run S2/S4."
        raise ValidationFailed([ClipIssue(CODE_SHOT_MISSING, shot.id, msg)])
    return clip


def _join(parts: list[tuple[str, str]]) -> str:
    return "; ".join(f"{label} {val}" for label, val in parts if val.strip())


def _lighting_text(lt: LightingSpec) -> str:
    return _join(
        [
            ("key:", lt.key),
            ("fill:", lt.fill),
            ("practicals:", lt.practicals),
            ("direction:", lt.direction),
            ("quality:", lt.quality),
        ]
    )


def _grade_text(cg: ColorGradeSpec) -> str:
    return _join(
        [
            ("shades:", ", ".join(cg.shades)),
            ("contrast:", cg.contrast),
            ("saturation:", cg.saturation),
            ("temperature:", cg.temperature),
        ]
    )


def build_look_lines(look: ShotLook | None, sg: StyleGuide, scene: Scene) -> LookLines:
    """Render the shot's look, falling back field-wise to the StyleGuide / scene mood."""
    lk = look or ShotLook()
    return LookLines(
        lighting=_lighting_text(lk.lighting) or sg.lighting_rules,
        color_grade=_grade_text(lk.color_grade) or f"palette {', '.join(sg.palette)}",
        mood=lk.mood or scene.mood,
        composition=lk.composition,
        camera_motion_intent=lk.camera_motion_intent,
    )
