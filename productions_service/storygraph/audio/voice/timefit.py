"""Time-fit TTS lines into their spoken slots without ever cutting words.

Tempo = tts/slot clamped to [tempo_min, tempo_max] (ffmpeg atempo). A line starts at its
slot onset (lip-sync anchor); if it would collide with the next line or the clip end it is
shifted earlier into free space before its slot. Any remainder is reported as overrun
(the audio is never trimmed).
"""

from __future__ import annotations

from dataclasses import dataclass

from .timing import LineSlot

MIN_SLOT_LEN_S = 0.05
LINE_GAP_S = 0.05


@dataclass(frozen=True)
class FitPlan:
    tempo: float
    start: float
    end: float
    overrun_s: float = 0.0


def plan_fit(
    tts_s: float,
    slot: tuple[float, float],
    free: tuple[float, float],
    tempo_bounds: tuple[float, float],
) -> FitPlan:
    """Fit a `tts_s`-long line into `slot` within the free interval `free` (seconds)."""
    lo, hi = tempo_bounds
    slot_len = max(slot[1] - slot[0], MIN_SLOT_LEN_S)
    tempo = min(hi, max(lo, tts_s / slot_len))
    length = tts_s / tempo
    start = max(slot[0], free[0])
    end = start + length
    if end > free[1]:
        shift = min(end - free[1], max(0.0, start - free[0]))
        start, end = start - shift, end - shift
    return FitPlan(round(tempo, 4), start, end, max(0.0, end - free[1]))


def place_lines(
    slots: list[LineSlot],
    tts_lengths: list[float],
    clip_s: float,
    tempo_bounds: tuple[float, float],
) -> list[FitPlan]:
    """Sequential placement: each line's free interval is (prev end, next slot start).

    A previous overrun never pushes a line past its own slot onset (lip sync wins over
    a short overlap, and later lines can never be pushed off the end of the clip).
    """
    plans: list[FitPlan] = []
    prev_end = 0.0
    for i, (slot, tts_s) in enumerate(zip(slots, tts_lengths, strict=True)):
        nxt = slots[i + 1].start - LINE_GAP_S if i + 1 < len(slots) else clip_s
        free = (min(prev_end, slot.start), max(nxt, slot.end))
        plan = plan_fit(tts_s, (slot.start, slot.end), free, tempo_bounds)
        plans.append(plan)
        prev_end = plan.end + LINE_GAP_S
    return plans
