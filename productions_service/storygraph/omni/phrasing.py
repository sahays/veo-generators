"""Spec -> plain-English phrase helpers for prose renderers of an `OmniClipSpec`.

Vocabulary follows the prompt-format A/B (`docs/eval/prompt_ab_v1.md`): plain cinematography
words (no `MCU` / `dolly_in` tokens), `<IMAGE_REF_k>` written right after the name it binds,
symbolic ids (`S1`, `O2`, `L1`) resolved to display names, and object states in plain words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .spec import CameraSpecOut, ObjectSpec, ObjectState, OmniClipSpec, StepSpec

SHOT_SIZES: Final[dict[str, str]] = {
    "ECU": "extreme close-up",
    "CU": "close-up",
    "MCU": "medium close-up",
    "MS": "medium shot",
    "MWS": "medium wide shot",
    "MLS": "medium-long shot",
    "FS": "full shot",
    "LS": "long shot",
    "WS": "wide shot",
    "EWS": "extreme wide shot",
    "ELS": "extreme long shot",
    "OTS": "over-the-shoulder shot",
    "POV": "point-of-view shot",
    "TWO": "two shot",
    "INSERT": "insert close-up",
}
ANGLES: Final[dict[str, str]] = {
    "eye": "at eye level",
    "eye_level": "at eye level",
    "low": "from a low angle looking up",
    "high": "from a high angle looking down",
    "overhead": "from directly overhead",
    "birds_eye": "from directly overhead",
    "dutch": "with a tilted dutch angle",
    "ground": "from ground level",
    "shoulder": "from shoulder height",
}
MOVES: Final[dict[str, str]] = {
    "static": "The camera is locked off and does not move",
    "locked": "The camera is locked off and does not move",
    "dolly_in": "The camera slowly dollies in toward {focus}",
    "push_in": "The camera slowly pushes in toward {focus}",
    "dolly_out": "The camera slowly dollies back from {focus}",
    "pull_out": "The camera slowly pulls back from {focus}",
    "track": "The camera tracks sideways, following {focus}",
    "truck": "The camera tracks sideways, following {focus}",
    "follow": "The camera follows {focus}",
    "pan": "The camera pans slowly to follow {focus}",
    "tilt": "The camera tilts slowly to follow {focus}",
    "crane": "The camera cranes smoothly over {focus}",
    "arc": "The camera arcs slowly around {focus}",
    "orbit": "The camera orbits slowly around {focus}",
    "zoom_in": "The camera slowly zooms in on {focus}",
    "zoom_out": "The camera slowly zooms out from {focus}",
    "handheld": "Gentle handheld camera on {focus}",
}
LANGS: Final[dict[str, str]] = {
    "hi": "Hindi",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "ru": "Russian",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
}
_ID_RE: Final[re.Pattern[str]] = re.compile(r"\b[SOL]\d+\b")
_ABBREV_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{2,6}$")
_MIN_WORDS: Final[int] = 3
_TERMINALS: Final[tuple[str, ...]] = (".", "!", "?", '"')


@dataclass(frozen=True)
class Names:
    """Symbolic id -> display name, and id -> inline `<IMAGE_REF_k>` tag."""

    name: dict[str, str]
    tag: dict[str, str]

    @classmethod
    def of(cls, spec: OmniClipSpec) -> Names:
        ents: list[tuple[str, str, str | None]] = [
            (s.id, s.name, s.ref_image) for s in spec.subjects or []
        ]
        ents += [(o.id, o.name, o.ref_image) for o in spec.objects or []]
        ents.append((spec.setting.id, spec.setting.name, spec.setting.ref_image))
        return cls(
            name={i: n for i, n, _ in ents},
            tag={i: f"<{r}>" for i, _, r in ents if r},
        )

    def tagged(self, ent_id: str) -> str:
        """`Pip <IMAGE_REF_0>` (name followed by its reference tag when bound)."""
        base = self.name.get(ent_id, ent_id)
        return f"{base} {self.tag[ent_id]}" if ent_id in self.tag else base

    def resolve(self, text: str) -> str:
        """Replace stray symbolic ids (S1, O2, L1) in free text with display names."""
        return _ID_RE.sub(lambda m: self.name.get(m.group(0), m.group(0)), text)


def usable(text: str | None) -> str:
    """Return `text` stripped, or '' when it is a truncated/garbage fragment."""
    t = (text or "").strip()
    if len(t.split()) < _MIN_WORDS or t.rstrip(".").endswith("-"):
        return ""
    return t if t.endswith((".", "!", "?")) else f"{t}."


def sentence(text: str) -> str:
    """Capitalised sentence ending in one terminal mark ('' stays '')."""
    t = text.strip()
    if not t:
        return ""
    t = t[0].upper() + t[1:]
    return t if t.endswith(_TERMINALS) else f"{t}."


def shot_size_words(size: str) -> str:
    """`MCU` -> `medium close-up`; unknown abbreviations never reach the prompt."""
    raw = size.strip()
    known = SHOT_SIZES.get(raw.upper().replace("-", "").replace(" ", ""))
    if known:
        return known
    return "medium shot" if _ABBREV_RE.match(raw) else raw.replace("_", " ").lower()


def camera_phrase(cam: CameraSpecOut, names: Names) -> str:
    """`Medium shot, at eye level, 35mm lens. The camera tracks sideways, following Pip.`"""
    angle = ANGLES.get(cam.angle.lower(), cam.angle.replace("_", " "))
    focus = names.name.get(cam.focus or "", "the action")
    move_key = cam.move.lower().replace(" ", "_")
    move = MOVES.get(move_key, f"The camera moves: {cam.move.replace('_', ' ')}")
    size = shot_size_words(cam.size)
    return f"{size[:1].upper()}{size[1:]}, {angle}, {cam.lens_mm}mm lens. {move.format(focus=focus)}."


def step_text(step: StepSpec, names: Names) -> str:
    """The beat as one active-voice sentence that names its actor."""
    verb = names.resolve(step.verb.strip().rstrip("."))
    actor = names.name.get(step.actor, step.actor)
    if not verb.lower().startswith(actor.lower()) and verb[:1].islower():
        verb = f"{actor} {verb}"
    return sentence(verb)


def lang_name(code: str) -> str:
    return LANGS.get(code.split("-")[0].lower(), code)


def state_words(state: ObjectState | None, names: Names) -> str:
    """Plain-word holder/place of one object state ('' when unknown or 'in place')."""
    if state is None:
        return ""
    if state.held_by:
        return f"held by {names.name.get(state.held_by, state.held_by)}"
    where = (state.where or "").strip().rstrip(".")
    if where in ("", "in_place"):
        return ""
    return names.resolve(where[0].lower() + where[1:])


def object_detail(obj: ObjectSpec, names: Names) -> str:
    """`Strawberry <IMAGE_REF_2>: at start in the bowl, at end held by Pip`."""
    start, end = state_words(obj.start, names), state_words(obj.end, names)
    parts = [f"at start {start}" if start else "", f"at end {end}" if end else ""]
    if not obj.moves:
        parts.append("stays in place")
    detail = ", ".join(p for p in parts if p)
    return names.tagged(obj.id) + (f": {detail}" if detail else "")
