"""Short prompt for the D_anchored strategy (one Omni call per clip, keyframe-anchored).

The bound images (first/last keyframe, optional timed middle keyframes) already carry identity,
wardrobe, props and layout, so the text keeps only what images cannot: the single-take rule,
the ordered beats, a name roster with screen sides, the camera move, dialogue and negatives.
`timeline` lines (D2) describe the middle keyframe states in words instead of images.
Names are plain (no `<IMAGE_REF_k>` tags): the adapter's role header binds the images.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from ...omni.phrasing import (
    Names,
    camera_phrase,
    lang_name,
    sentence,
    step_text,
    usable,
)
from ...omni.relevance import prompt_objects
from ...omni.render_hybrid import NEGATIVES, SINGLE_TAKE, plain_beat, speech_slot
from ...omni.spec import OmniClipSpec
from ..plan.models import Keyframe, KeyframePlan

ANCHOR_LINE: Final[str] = (
    "<FIRST_FRAME> The video starts exactly on the first keyframe and <LAST_FRAME> ends "
    "exactly on the last keyframe."
)
STATE_REF_LINE: Final[str] = (
    "Images tagged IMAGE_REF are timed state references inside this one continuous take "
    "(where everyone and everything is at that second), never shots to insert or cut to."
)
APPEARANCE: Final[str] = "appearance and outfit exactly as in the keyframes"


def _prose(spec: OmniClipSpec, names: Names, state_refs: bool) -> str:
    steps = sorted(spec.sequence or [], key=lambda s: s.n)
    parts = [
        SINGLE_TAKE,
        sentence(usable(spec.clip.style)),
        ANCHOR_LINE,
        STATE_REF_LINE if state_refs else "",
        *(plain_beat(step_text(s, names)) for s in steps),
    ]
    return " ".join(p for p in parts if p)


def _roster(spec: OmniClipSpec) -> list[str]:
    chars = [
        f"- {s.name} ({s.screen_pos} of frame): {APPEARANCE}"
        for s in spec.subjects or []
    ]
    objs = ", ".join(o.name for o in prompt_objects(spec))
    out = ["CHARACTERS:", *chars] if chars else []
    return out + (
        [f"OBJECTS (each exactly one, as in the keyframes): {objs}"] if objs else []
    )


def dialogue_lines(spec: OmniClipSpec, names: Names) -> list[str]:
    lines = [
        f"- {speech_slot(s.after)}, {names.name.get(s.speaker, s.speaker)} "
        f'({lang_name(s.lang)}, {s.voice}): "{s.text}"'
        for s in spec.speech or []
    ]
    return ["DIALOGUE:", *lines] if lines else []


def render_anchored(
    spec: OmniClipSpec, timeline: Sequence[str] = (), state_refs: bool = False
) -> str:
    """D_anchored prompt: beats + roster + camera + dialogue (+ D2 timeline text)."""
    names = Names(name=Names.of(spec).name, tag={})
    block = [
        *_roster(spec),
        f"SETTING: {spec.setting.name}",
        f"CAMERA: {camera_phrase(spec.camera, names)}",
        *(["TIMELINE (pass through these states):", *timeline] if timeline else []),
        *dialogue_lines(spec, names),
    ]
    return "\n".join([_prose(spec, names, state_refs), "", *block, NEGATIVES])


def anchor_times(last_t: int, slots: int) -> list[int]:
    """Up to `slots` evenly spaced interior seconds of 0..last_t (distinct, ascending)."""
    if last_t < 2 or slots <= 0:
        return []
    picks = {round(i * last_t / (slots + 1)) for i in range(1, slots + 1)}
    return sorted(t for t in picks if 0 < t < last_t)


def timeline_lines(plan: KeyframePlan, times: Sequence[int]) -> list[str]:
    """One sentence per chosen keyframe: who does what, who holds what (from the plan)."""
    return [f"- at {t}s: {_state_sentence(plan.at(t))}" for t in times]


def _state_sentence(frame: Keyframe) -> str:
    names = {o.entity_id: o.name for o in frame.objects}
    parts = [
        f"{c.name} {c.pose.rstrip('.')}"
        + (
            f", holding {', '.join(names.get(h, h) for h in c.holding)}"
            if c.holding
            else ""
        )
        for c in frame.characters
    ]
    return "; ".join(parts)
