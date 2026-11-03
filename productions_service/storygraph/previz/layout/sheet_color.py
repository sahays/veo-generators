"""Dominant subject colour of a reference sheet (pure, deterministic, O(pixels)).

Reference sheets are drawn on pastel / diorama backgrounds, so "not white" is not enough.
The background is estimated from the image's border band (the 5 % ring): its most frequent
3-bit buckets (covering 85 % of the ring, at most four) are background, and every pixel close
to one of them is dropped. Remaining pixels vote in a 3-bit-per-channel histogram weighted
by chroma (saturated subject colours beat skin/shadow greys) and by proximity to the centre
(the subject sits in the middle of a sheet). The answer is the weighted mean of the modal
bucket (ties -> lowest key). Returns None when nothing but background remains.
"""

from __future__ import annotations

import io
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from PIL import Image, UnidentifiedImageError

THUMB: Final[int] = 96
BAND: Final[float] = 0.05
BG_COVER: Final[float] = 0.85
BG_MAX: Final[int] = 4
BG_DIST2: Final[int] = 36**2
MIN_CHROMA: Final[int] = 12
Rgb = tuple[int, int, int]
Key = tuple[int, int, int]


@dataclass(frozen=True)
class Sheet:
    width: int
    height: int
    pixels: list[Rgb]  # row-major


def load_sheet(png: bytes) -> Sheet | None:
    try:
        img = Image.open(io.BytesIO(png)).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    img.thumbnail((THUMB, THUMB), Image.Resampling.NEAREST)
    raw = img.tobytes()
    pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
    return Sheet(img.width, img.height, pixels)


def _key(p: Rgb) -> Key:
    return p[0] >> 5, p[1] >> 5, p[2] >> 5


def _mean(pixels: Sequence[Rgb]) -> Rgb:
    n = len(pixels)
    return (
        sum(p[0] for p in pixels) // n,
        sum(p[1] for p in pixels) // n,
        sum(p[2] for p in pixels) // n,
    )


def _border(sheet: Sheet) -> list[Rgb]:
    band = max(1, round(BAND * min(sheet.width, sheet.height)))
    w, h = sheet.width, sheet.height
    return [
        p
        for i, p in enumerate(sheet.pixels)
        if not (band <= i % w < w - band and band <= i // w < h - band)
    ]


def background(sheet: Sheet) -> list[Rgb]:
    """Mean colours of the border ring's dominant buckets."""
    ring = _border(sheet)
    groups: dict[Key, list[Rgb]] = {}
    for p in ring:
        groups.setdefault(_key(p), []).append(p)
    out: list[Rgb] = []
    covered = 0
    for key, _ in sorted(
        Counter(_key(p) for p in ring).items(), key=lambda kv: (-kv[1], kv[0])
    ):
        out.append(_mean(groups[key]))
        covered += len(groups[key])
        if covered >= BG_COVER * len(ring) or len(out) >= BG_MAX:
            break
    return out


def near_any(p: Rgb, colours: Sequence[Rgb]) -> bool:
    return any(
        sum((a - b) ** 2 for a, b in zip(p, c, strict=True)) < BG_DIST2 for c in colours
    )


def _weight(sheet: Sheet, i: int, p: Rgb, bg: Sequence[Rgb]) -> float:
    chroma = max(p) - min(p)
    if chroma < MIN_CHROMA or near_any(p, bg):
        return 0.0
    dx = (i % sheet.width + 0.5) / sheet.width - 0.5
    dy = (i // sheet.width + 0.5) / sheet.height - 0.5
    centre = max(0.0, 1.0 - math.hypot(dx, dy) / 0.7)
    return chroma / 255 * (0.25 + 0.75 * centre)


def subject_color(sheet: Sheet) -> Rgb | None:
    """Weighted modal colour of the non-background pixels (None if there are none)."""
    bg = background(sheet)
    votes: dict[Key, float] = {}
    members: dict[Key, list[tuple[Rgb, float]]] = {}
    for i, p in enumerate(sheet.pixels):
        w = _weight(sheet, i, p, bg)
        if w > 0.0:
            votes[_key(p)] = votes.get(_key(p), 0.0) + w
            members.setdefault(_key(p), []).append((p, w))
    if not votes:
        return None
    best = min(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    total = votes[best]
    return (
        round(sum(p[0] * w for p, w in members[best]) / total),
        round(sum(p[1] * w for p, w in members[best]) / total),
        round(sum(p[2] * w for p, w in members[best]) / total),
    )
