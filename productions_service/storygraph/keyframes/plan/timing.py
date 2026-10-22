"""Clip clock: allocate seconds to beats from step duration hints and locate second `t`.

Beats share the clip proportionally to their `duration_hint_s` (cumulative sums, so spans
are contiguous and end exactly at the clip duration). `locate` finds the beat active at a
second with a binary search over beat end times (O(log beats)).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from itertools import accumulate

_MIN_HINT_S = 0.5


def allocate_spans(
    hints: Sequence[float], duration_s: float
) -> list[tuple[float, float]]:
    """Contiguous `(start, end)` per beat, proportional to `hints`, covering `duration_s`."""
    if not hints:
        return []
    weights = [max(_MIN_HINT_S, float(h)) for h in hints]
    total = sum(weights)
    ends = [round(duration_s * c / total, 3) for c in accumulate(weights)]
    ends[-1] = round(duration_s, 3)
    starts = [0.0, *ends[:-1]]
    return list(zip(starts, ends, strict=True))


def second_count(duration_s: float) -> int:
    """Number of 1 fps keyframes for a clip: t = 0..round(duration) inclusive."""
    return max(1, round(duration_s)) + 1


def locate(t: float, spans: Sequence[tuple[float, float]]) -> tuple[int, float]:
    """`(beat index, phase in [0, 1])` of second `t`; the clip end maps to the last beat."""
    if not spans:
        return 0, 0.0
    ends = [end for _, end in spans]
    idx = min(bisect_right(ends, t), len(spans) - 1)
    start, end = spans[idx]
    width = end - start
    phase = 1.0 if width <= 0 else (t - start) / width
    return idx, round(min(1.0, max(0.0, phase)), 3)


def snapshot_index(beat_index: int, phase: float) -> int:
    """Graph snapshot shown at a phase: pre-beat state before the midpoint, post-beat after.

    Snapshot `i` is the state before beat `i`; `i + 1` the state after it. Discrete changes
    (hand-offs, placements) therefore switch at the beat midpoint, never mid-air twice.
    """
    return beat_index + (1 if phase >= 0.5 else 0)
