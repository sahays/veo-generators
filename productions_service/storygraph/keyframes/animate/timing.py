"""Pure timing/layout helpers for keyframe animation (animatic schedule, interp segments)."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

OMNI_MIN_S = 3
OMNI_MAX_S = 10
EPS = 1e-6


def animatic_schedule(times: Sequence[float], duration_s: float) -> list[float]:
    """Display time per keyframe so each keyframe is on screen around its own time.

    Keyframe `i` (at ascending `times[i]`, possibly uneven event times) is shown from the
    midpoint with its predecessor to the midpoint with its successor; the first starts at 0
    and the last ends at `duration_s`, so the animatic lasts exactly `duration_s`.
    """
    if len(times) <= 1:
        return [round(duration_s, 3)] * max(1, len(times))
    mids = [(a + b) / 2 for a, b in itertools.pairwise(times)]
    edges = [0.0, *mids, duration_s]
    return [round(b - a, 3) for a, b in itertools.pairwise(edges)]


def concat_manifest(paths: Sequence[str], durations: Sequence[float]) -> str:
    """ffmpeg concat-demuxer manifest (the last file is repeated so its duration applies)."""
    lines: list[str] = []
    for path, dur in zip(paths, durations, strict=True):
        lines += [f"file '{path}'", f"duration {dur:.3f}"]
    if paths:
        lines.append(f"file '{paths[-1]}'")
    return "\n".join(lines) + "\n"


def _marks(times: Sequence[float], stride: float) -> list[int]:
    """Greedy keyframe indices at least `stride` seconds apart, always first and last."""
    marks = [0]
    for i in range(1, len(times)):
        if times[i] - times[marks[-1]] >= stride - EPS:
            marks.append(i)
    if marks[-1] != len(times) - 1:
        marks.append(len(times) - 1)
    return marks


def segment_bounds(times: Sequence[float], stride: int) -> list[tuple[int, int]]:
    """`(start, end)` keyframe INDICES of each interpolation segment covering the clip.

    `times` are the ascending keyframe times. Segments span at least `stride` seconds
    (one greedy pass, O(n)); a tail shorter than Omni's minimum duration is merged into the
    previous segment (when that stays within Omni's maximum) or stands alone.
    """
    if len(times) < 2:
        return []
    bounds = list(itertools.pairwise(_marks(times, max(OMNI_MIN_S, stride))))
    if len(bounds) >= 2:
        (a, _), (b, end) = bounds[-2], bounds[-1]
        tail = times[end] - times[b]
        if tail < OMNI_MIN_S - EPS and times[end] - times[a] <= OMNI_MAX_S + EPS:
            bounds[-2:] = [(a, end)]
    return bounds
