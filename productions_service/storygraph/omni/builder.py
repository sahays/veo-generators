"""Assemble the typed `OmniClipSpec` for one shot/clip at a given description level.

Budget trimming walks `DESC_LEVELS`: identity strings shrink first, then optional look /
summary extras. `sequence` and `speech` are never trimmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..clips.models import ClipScript
from ..clips.prompt_ctx import build_look_lines
from ..views import ShotView
from .props import build_objects
from .sequence import build_sequence, clip_steps
from .sound import select_sounds
from .spec import (
    AudioSpec,
    CameraSpecOut,
    ClipSpec,
    ConstraintToken,
    ContinuitySpec,
    LookSpec,
    OmniClipSpec,
    SettingSpec,
    SpeechSpec,
)
from .subjects import build_speakers, build_speech, build_subjects
from .symbols import ImageBindings, Symbols
from .text import clean, condense_identity, first_sentence

_BASE_CONSTRAINTS: Final[tuple[ConstraintToken, ...]] = (
    "sequence_order_strict",
    "single_continuous_take",
)
_OBJECT_CONSTRAINTS: Final[tuple[ConstraintToken, ...]] = (
    "each_object_single_instance",
    "objects_static_unless_in_sequence",
)


@dataclass(frozen=True)
class DescPolicy:
    """Identity sentences per entity + optional extras; the budget walks down these levels."""

    with_ref: int
    without_ref: int
    setting: int
    props: int
    extras: bool = True


DESC_LEVELS: Final[tuple[DescPolicy, ...]] = (
    DescPolicy(2, 2, 2, 2),
    DescPolicy(1, 2, 1, 1),
    DescPolicy(1, 1, 1, 1),
    DescPolicy(1, 1, 1, 1, extras=False),
    DescPolicy(1, 1, 0, 1, extras=False),
)  # subject/object identity never drops below one sentence (review Theme 2.7)


def _setting(view: ShotView, sym: Symbols, b: ImageBindings, n: int) -> SettingSpec:
    r = sym.resolver
    ident = condense_identity(view.location_appearance.visual_description, r, [], n)
    return SettingSpec(
        id=sym.ids[view.location.id],
        name=view.location.canonical_name,
        ref_image=b.ref_by_entity.get(view.location.id),
        identity=ident or None,
        time_of_day=clean(view.scene.time_of_day, r) or None,
        weather=clean(view.scene.weather, r) or None,
    )


def _camera(view: ShotView, sym: Symbols, extras: bool) -> CameraSpecOut:
    cam = view.shot.camera
    intent = (
        clean(view.shot.look.camera_motion_intent, sym.resolver)
        if view.shot.look
        else ""
    )
    return CameraSpecOut(
        size=cam.shot_size,
        angle=cam.angle,
        move=cam.movement,
        lens_mm=cam.lens_mm,
        focus=sym.ref(cam.focus_target_id),
        intent=intent if intent and extras else None,
    )


def _look(view: ShotView, sym: Symbols, extras: bool) -> LookSpec | None:
    lk = build_look_lines(view.shot.look, view.style_guide, view.scene)
    r = sym.resolver
    look = LookSpec(
        lighting=clean(lk.lighting, r) or None,
        color_grade=clean(lk.color_grade, r) or None,
        mood=clean(lk.mood, r) or None,
        composition=(clean(lk.composition, r) or None) if extras else None,
    )
    return look if look.model_dump(exclude_none=True) else None


def _continuity(
    view: ShotView, clip: ClipScript, sym: Symbols, b: ImageBindings
) -> ContinuitySpec | None:
    prev = next(
        (c for c in view.scene.clips if c.clip_index == clip.clip_index - 1), None
    )
    state = clean(prev.closing_state if prev else "", sym.resolver) or clean(
        clip.opening_state, sym.resolver
    )
    if not (state or b.first_frame):
        return None
    return ContinuitySpec(
        first_frame="FIRST_FRAME" if b.first_frame else None,
        opening_state=state.rstrip(".") or None,
    )


def _constraints(
    view: ShotView, b: ImageBindings, has_objects: bool, speech: list[SpeechSpec]
) -> list[ConstraintToken]:
    out = list(_BASE_CONSTRAINTS)
    out += list(_OBJECT_CONSTRAINTS) if has_objects else []
    out.append("no_text_overlays")
    out += ["refs_are_identity_only"] if b.ref_by_entity else []
    out += ["first_frame_is_opening_frame"] if b.first_frame else []
    lip = any(s.lipsync for s in speech) and len(view.shot.cast) > 1
    return out + (["lipsync_active_speaker_only"] if lip else [])


def _clip(view: ShotView, sym: Symbols, sfx: list[str]) -> ClipSpec:
    sg = view.style_guide
    return ClipSpec(
        duration_s=view.shot.duration_s,
        aspect=sg.aspect_ratio,
        fps=sg.fps,
        style=first_sentence(sg.visual_medium, sym.resolver) or None,
        audio=AudioSpec(music=False, sfx=sfx or None),
    )


def build_spec(
    view: ShotView,
    clip: ClipScript,
    bindings: ImageBindings,
    policy: DescPolicy,
    retry_feedback: list[str] | None,
    extra_constraints: tuple[ConstraintToken, ...] = (),
) -> OmniClipSpec:
    """Typed, validated machine spec for the clip this shot renders."""
    sym = Symbols(view)
    steps = clip_steps(view, clip)
    spk = build_speakers(view, sym)
    sequence = build_sequence(steps, sym)
    speech = build_speech(view, spk, sym, clip.omni_prompt, sequence)
    objects = build_objects(view, clip, steps, sym, bindings, policy.props)
    sfx = [
        clean(s, sym.resolver)
        for s in select_sounds(view.shot, steps, clip.omni_prompt)
    ]
    summary = clean(clip.omni_prompt, sym.resolver)
    goals = [
        g
        for g in (clean(f, sym.resolver).rstrip(".") for f in retry_feedback or [])
        if g
    ]
    subjects = build_subjects(
        view, spk, sym, bindings, policy.with_ref, policy.without_ref, policy.extras
    )
    constraints = _constraints(view, bindings, bool(objects), speech)
    return OmniClipSpec(
        clip=_clip(view, sym, [s for s in sfx if s]),
        subjects=subjects or None,
        setting=_setting(view, sym, bindings, policy.setting),
        objects=objects or None,
        camera=_camera(view, sym, policy.extras),
        look=_look(view, sym, policy.extras),
        continuity=_continuity(view, clip, sym, bindings),
        sequence=sequence or None,
        summary=summary if summary and (policy.extras or not sequence) else None,
        speech=speech or None,
        constraints=list(dict.fromkeys([*constraints, *extra_constraints])),
        must_achieve=goals or None,
    )
