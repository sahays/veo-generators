"""Spec -> natural-language phrase helpers shared by every prose variant.

Vocabulary follows the Gemini Omni prompt guide: plain cinematography words for shot size,
angle and movement, `<IMAGE_REF_k>` written right after the noun it binds, explicit
"single continuous shot / no scene cuts", timecoded beats, and short literal negatives.
The shared vocabulary now lives in production (`storygraph.omni.phrasing`); this module
keeps only the experiment-specific helpers (timecode windows, inline speech).
"""

from __future__ import annotations

import itertools

from ....omni.phrasing import (
    Names,
    lang_name,
    object_detail,
    sentence,
    step_text,
    usable,
)
from ....omni.phrasing import camera_phrase as _camera_words
from ....omni.spec import ObjectSpec, OmniClipSpec, SpeechSpec

__all__ = [
    "Names",
    "beat_windows",
    "camera_phrase",
    "fmt_s",
    "lang_name",
    "object_line",
    "sentence",
    "speech_text",
    "step_text",
    "usable",
]


def camera_phrase(spec: OmniClipSpec, names: Names) -> str:
    return _camera_words(spec.camera, names)


def speech_text(line: SpeechSpec, names: Names, voice: bool = True) -> str:
    """`Pip says in Hindi, bright robotic voice, warm: "..."` (`voice=False`: no timbre)."""
    who = names.name.get(line.speaker, line.speaker)
    how = ", ".join(p for p in (line.voice, line.delivery) if p) if voice else ""
    how_part = f", {how}" if how else ""
    return f'{who} says in {lang_name(line.lang)}{how_part}: "{line.text}"'


def object_line(obj: ObjectSpec, names: Names) -> str:
    """`exactly one Strawberry <IMAGE_REF_2>: starts in the bowl, ends held by Pip`."""
    return f"exactly one {object_detail(obj, names)}"


def beat_windows(duration_s: float, n: int) -> list[tuple[float, float]]:
    """Equal, half-second-rounded timecode windows covering the clip."""
    if n <= 0:
        return []
    step = duration_s / n
    edges = [round(i * step * 2) / 2 for i in range(n)] + [round(duration_s, 1)]
    return list(itertools.pairwise(edges))


def fmt_s(value: float) -> str:
    return f"{value:g}s"
