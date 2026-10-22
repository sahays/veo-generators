"""Pure drift metrics from a `ClipObservation` (per-frame counts -> rates)."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from .contracts import ClipObservation, FrameObs

CHEST = "wooden chest"
CABINET = "blue cabinet"


def _count(frame: FrameObs, name: str) -> int:
    return next((o.count for o in frame.objects if o.name.lower() == name), 0)


def _rate(flags: Sequence[bool]) -> float:
    return round(sum(flags) / len(flags), 3) if flags else 0.0


def flicker(present: Sequence[bool]) -> int:
    """Number of present<->absent transitions (vanish / pop-in events)."""
    return sum(1 for a, b in itertools.pairwise(present) if a != b)


def drift_metrics(obs: ClipObservation) -> dict[str, float | int]:
    frames = obs.frames
    chest = [_count(f, CHEST) for f in frames]
    cabinet = [_count(f, CABINET) >= 1 for f in frames]
    chars = [c for f in frames for c in f.characters]
    return {
        "frames": len(frames),
        "chest_dup_rate": _rate([n > 1 for n in chest]),
        "chest_present_rate": _rate([n >= 1 for n in chest]),
        "cabinet_present_rate": _rate(cabinet),
        "cabinet_flicker": flicker(cabinet),
        "outfit_stability": _rate([c.outfit_matches for c in chars if c.present]),
        "identity_presence": _rate([c.present for c in chars]),
        "extra_char_rate": _rate([f.extra_characters > 0 for f in frames]),
        "action_adherence": _rate(obs.beats_done),
    }
