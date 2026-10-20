"""Deterministic temporal metrics from densely sampled frames (no VLM).

All series are O(n) over the sampled frames: consecutive-frame L1 differences give freezes and
jumps; the A-B-A pattern (frame i ~ frame i+2 while i -> i+1 differs) gives flicker.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from ...adapters.media_frames import ClipProbe, mean_l1_diff

FREEZE_DIFF = 0.25
MIN_FREEZE_S = 1.5
FLICKER_STEP = 12.0
FLICKER_RETURN_RATIO = 0.35
JUMP_FLOOR = 20.0
JUMP_MEDIAN_X = 4.0
CUT_GUARD_S = 0.3


@dataclass(frozen=True)
class VideoMetrics:
    """Temporal measurements; `available=False` when the clip could not be decoded."""

    available: bool = False
    duration_s: float = 0.0
    requested_s: float = 0.0
    cut_times_s: tuple[float, ...] = ()
    frame_times: tuple[float, ...] = ()
    diffs: tuple[float, ...] = ()
    freeze_spans: tuple[tuple[float, float], ...] = ()
    flicker_times: tuple[float, ...] = ()
    jump_times: tuple[float, ...] = ()

    @property
    def duration_ratio(self) -> float:
        """Rendered / requested duration (1.0 when either is unknown)."""
        if self.duration_s <= 0 or self.requested_s <= 0:
            return 1.0
        return self.duration_s / self.requested_s


def _diff_series(pngs: list[bytes], step: int) -> list[float]:
    """L1 difference between frame i and i+step (unreadable pairs count as 0)."""
    return [
        mean_l1_diff(pngs[i], pngs[i + step]) or 0.0 for i in range(len(pngs) - step)
    ]


def freeze_spans(times: list[float], diffs: list[float]) -> list[tuple[float, float]]:
    """Maximal runs of near-identical consecutive frames lasting >= MIN_FREEZE_S."""
    spans: list[tuple[float, float]] = []
    start: int | None = None
    for i, d in enumerate([*diffs, FREEZE_DIFF + 1.0]):
        if d < FREEZE_DIFF and start is None:
            start = i
        elif d >= FREEZE_DIFF and start is not None:
            if times[i] - times[start] >= MIN_FREEZE_S:
                spans.append((times[start], times[i]))
            start = None
    return spans


def flicker_times(
    times: list[float], step1: list[float], step2: list[float]
) -> list[float]:
    """Times where a frame jumps away and the next frame returns (A-B-A flicker)."""
    return [
        times[i + 1]
        for i in range(len(step2))
        if step1[i] > FLICKER_STEP and step2[i] < FLICKER_RETURN_RATIO * step1[i]
    ]


def jump_times(
    times: list[float],
    diffs: list[float],
    cuts: tuple[float, ...],
    flicker: list[float],
) -> list[float]:
    """Large single-step changes that are neither scene cuts nor flicker (pose/position jumps)."""
    if len(diffs) < 3:
        return []
    floor = max(JUMP_FLOOR, JUMP_MEDIAN_X * median(diffs))
    excluded = [*cuts, *flicker]
    return [
        times[i + 1]
        for i, d in enumerate(diffs)
        if d > floor and all(abs(times[i + 1] - t) > CUT_GUARD_S for t in excluded)
    ]


def compute_video_metrics(probe: ClipProbe, requested_s: float) -> VideoMetrics:
    """Temporal metrics for a decoded clip (synthetic fallback probes are unavailable)."""
    if probe.duration_s <= 0.0 or len(probe.frames) < 2:
        return VideoMetrics(requested_s=requested_s)
    frames = sorted(probe.frames, key=lambda f: f.t_s)
    times = [f.t_s for f in frames]
    pngs = [f.png for f in frames]
    step1, step2 = _diff_series(pngs, 1), _diff_series(pngs, 2)
    flicker = flicker_times(times, step1, step2)
    return VideoMetrics(
        available=True,
        duration_s=probe.duration_s,
        requested_s=requested_s,
        cut_times_s=probe.cut_times_s,
        frame_times=tuple(times),
        diffs=tuple(round(d, 3) for d in step1),
        freeze_spans=tuple(freeze_spans(times, step1)),
        flicker_times=tuple(flicker),
        jump_times=tuple(jump_times(times, step1, probe.cut_times_s, flicker)),
    )
