"""Actual clip timing for assembly: probed durations, not the planned `Shot.duration_s`.

Rendered clips typically come back 0.4–1 s shorter than requested, so every timing
decision (music segment boundaries, crossfades) uses the measured length; the planned
length is only a fallback when ffprobe cannot read a clip.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from ..repo import Repo
from .readiness import ReadyShot

logger = logging.getLogger(__name__)

DurationProbe = Callable[[bytes], float | None]
_DRIFT_LOG_THRESHOLD_S: Final[float] = 0.25


@dataclass(frozen=True)
class ClipTiming:
    shot_id: str
    planned_s: float
    actual_s: float
    probed: bool


def measure_clip_timings(
    repo: Repo, ready: list[ReadyShot], clips: list[bytes], probe: DurationProbe
) -> list[ClipTiming]:
    """Probe each stitched clip once; fall back to the planned duration when unreadable."""
    timings: list[ClipTiming] = []
    for r, clip in zip(ready, clips, strict=True):
        shot = repo.get_shot(r.shot_id)
        planned = shot.duration_s if shot else 0.0
        measured = probe(clip)
        ok = measured is not None and measured > 0
        timings.append(ClipTiming(r.shot_id, planned, measured if ok else planned, ok))
    _log_drift(repo, timings)
    return timings


def _log_drift(repo: Repo, timings: list[ClipTiming]) -> None:
    drifted = {
        t.shot_id: round(t.actual_s - t.planned_s, 3)
        for t in timings
        if t.probed and abs(t.actual_s - t.planned_s) >= _DRIFT_LOG_THRESHOLD_S
    }
    unprobed = [t.shot_id for t in timings if not t.probed]
    if not drifted and not unprobed:
        return
    logger.info(
        "Clip durations differ from plan; using probed lengths",
        extra={
            "who": "storygraph.assembly",
            "where": "assembly.timing",
            "what": "clip_duration_drift",
            "when": datetime.now(UTC).isoformat(),
            "why": "rendered clips are shorter/longer than Shot.duration_s",
            "how": "ffprobe format=duration per clip",
            "project_id": repo.project_id,
            "drift_s_by_shot": drifted,
            "unprobed_shot_ids": unprobed,
        },
    )
