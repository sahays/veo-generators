"""Spec -> natural-language phrase helpers shared by every prose variant.

Vocabulary follows the Gemini Omni prompt guide: plain cinematography words for shot size,
angle and movement, `<IMAGE_REF_k>` written right after the noun it binds, explicit
"single continuous shot / no scene cuts", timecoded beats, and short literal negatives.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from ....omni.spec import ObjectSpec, ObjectState, OmniClipSpec, SpeechSpec, StepSpec

SHOT_SIZES: dict[str, str] = {
    "ECU": "extreme close-up",
    "CU": "close-up",
    "MCU": "medium close-up",
    "MS": "medium shot",
    "MLS": "medium-long shot",
    "LS": "long shot",
    "WS": "wide shot",
    "EWS": "extreme wide shot",
}
ANGLES: dict[str, str] = {
    "eye": "at eye level",
    "low": "from a low angle looking up",
    "high": "from a high angle looking down",
    "overhead": "from directly overhead",
    "dutch": "with a tilted dutch angle",
}
MOVES: dict[str, str] = {
    "static": "The camera is locked off and does not move",
    "dolly_in": "The camera slowly dollies in toward {focus}",
    "dolly_out": "The camera slowly dollies back from {focus}",
    "track": "The camera tracks sideways, following {focus}",
    "pan": "The camera pans slowly to follow {focus}",
    "tilt": "The camera tilts slowly to follow {focus}",
    "handheld": "Gentle handheld camera on {focus}",
}
LANGS: dict[str, str] = {
    "hi": "Hindi",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ja": "Japanese",
}
_ID_RE = re.compile(r"\b[SOL]\d+\b")
_MIN_WORDS = 3


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
    if len(t.split()) < _MIN_WORDS or t.endswith("-."):
        return ""
    return t if t.endswith((".", "!", "?")) else f"{t}."


def sentence(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    t = t[0].upper() + t[1:]
    return t if t.endswith((".", "!", "?", '"')) else f"{t}."


def camera_phrase(spec: OmniClipSpec, names: Names) -> str:
    cam = spec.camera
    size = SHOT_SIZES.get(cam.size.upper(), cam.size)
    angle = ANGLES.get(cam.angle, cam.angle)
    focus = names.name.get(cam.focus or "", "the action")
    move = MOVES.get(cam.move, cam.move.replace("_", " ")).format(focus=focus)
    return f"{size.capitalize()}, {angle}, {cam.lens_mm}mm lens. {move}."


def step_text(step: StepSpec, names: Names) -> str:
    """The beat as one active-voice sentence that names its actor."""
    verb = names.resolve(step.verb.strip().rstrip("."))
    actor = names.name.get(step.actor, step.actor)
    if not verb.lower().startswith(actor.lower()) and verb[:1].islower():
        verb = f"{actor} {verb}"
    return sentence(verb)


def lang_name(code: str) -> str:
    return LANGS.get(code.split("-")[0].lower(), code)


def speech_text(line: SpeechSpec, names: Names, voice: bool = True) -> str:
    """`Pip says in Hindi, bright robotic voice, warm: "..."` (`voice=False`: no timbre)."""
    who = names.name.get(line.speaker, line.speaker)
    how = ", ".join(p for p in (line.voice, line.delivery) if p) if voice else ""
    how_part = f", {how}" if how else ""
    return f'{who} says in {lang_name(line.lang)}{how_part}: "{line.text}"'


def _state(state: ObjectState | None, names: Names) -> str:
    if state is None:
        return ""
    if state.held_by:
        return f"held by {names.name.get(state.held_by, state.held_by)}"
    where = (state.where or "").strip().rstrip(".")
    if where in ("", "in_place"):
        return ""
    return names.resolve(where[0].lower() + where[1:])


def object_line(obj: ObjectSpec, names: Names) -> str:
    """`exactly one Strawberry <IMAGE_REF_2>: starts in the bowl, ends held by Pip`."""
    start, end = _state(obj.start, names), _state(obj.end, names)
    parts = [f"at start {start}" if start else "", f"at end {end}" if end else ""]
    if not obj.moves:
        parts.append("stays in place")
    detail = ", ".join(p for p in parts if p)
    return f"exactly one {names.tagged(obj.id)}" + (f": {detail}" if detail else "")


def beat_windows(duration_s: float, n: int) -> list[tuple[float, float]]:
    """Equal, half-second-rounded timecode windows covering the clip."""
    if n <= 0:
        return []
    step = duration_s / n
    edges = [round(i * step * 2) / 2 for i in range(n)] + [round(duration_s, 1)]
    return list(itertools.pairwise(edges))


def fmt_s(value: float) -> str:
    return f"{value:g}s"
