"""Pure timing/layout helpers for keyframe animation (animatic schedule, interp segments)."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

OMNI_MIN_S = 3
OMNI_MAX_S = 10


def animatic_schedule(n_frames: int, duration_s: float) -> list[float]:
    """Display time per keyframe so keyframe `t` is centred on second `t` of the clip.

    Keyframes sit at t = 0..N (N = n_frames - 1): the first and last are shown for half a
    step, the rest for a full step, so the animatic lasts exactly `duration_s`.
    """
    if n_frames <= 1:
        return [round(duration_s, 3)] * max(1, n_frames)
    step = duration_s / (n_frames - 1)
    return [round(step / 2, 3), *[round(step, 3)] * (n_frames - 2), round(step / 2, 3)]


def concat_manifest(paths: Sequence[str], durations: Sequence[float]) -> str:
    """ffmpeg concat-demuxer manifest (the last file is repeated so its duration applies)."""
    lines: list[str] = []
    for path, dur in zip(paths, durations, strict=True):
        lines += [f"file '{path}'", f"duration {dur:.3f}"]
    if paths:
        lines.append(f"file '{paths[-1]}'")
    return "\n".join(lines) + "\n"


def segment_bounds(last_t: int, stride: int) -> list[tuple[int, int]]:
    """`(start, end)` keyframe seconds of each interpolation segment covering 0..last_t.

    Segments are `stride` seconds; a remainder shorter than Omni's minimum duration is merged
    into the previous segment (when that stays within Omni's maximum) or stands alone.
    """
    stride = max(OMNI_MIN_S, stride)
    marks = list(range(0, last_t, stride)) + [last_t]
    bounds = list(itertools.pairwise(marks))
    if len(bounds) >= 2:
        (a, _), (_, end) = bounds[-2], bounds[-1]
        tail = bounds[-1][1] - bounds[-1][0]
        if tail < OMNI_MIN_S and end - a <= OMNI_MAX_S:
            bounds[-2:] = [(a, end)]
    return bounds
