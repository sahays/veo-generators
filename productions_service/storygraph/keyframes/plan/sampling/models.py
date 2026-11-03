"""Typed contracts for keyframe time sampling: config, candidate moments and priorities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final, Literal, Self

from pydantic import BaseModel, Field, model_validator

from ..models import EventKind

SamplingMode = Literal["events", "fps"]

# Selection priority: graph/plan state changes > beat boundaries > motion / gap fillers.
ENDPOINT: Final[int] = 100
STATE: Final[int] = 3
BEAT: Final[int] = 2
MOTION: Final[int] = 1
FILLER: Final[int] = 0

# Tie-break inside one priority (lower = more important); also orders combined labels.
KIND_RANK: Final[dict[EventKind, int]] = {
    "clip_start": 0,
    "clip_end": 0,
    "hand_over": 1,
    "pick_up": 2,
    "put_down": 3,
    "entrance": 4,
    "exit": 5,
    "open_close": 6,
    "on_off": 7,
    "reveal": 8,
    "hide": 9,
    "location": 10,
    "contact": 11,
    "beat_start": 12,
    "beat_end": 13,
    "motion": 14,
    "interpolated": 15,
}


class SamplingCfg(BaseModel):
    """How keyframe times are chosen (mirrors config `keyframes.*`, resolved by the stage).

    * `events`: clip start/end + state changes, beat boundaries and large-motion midpoints,
      merged within `min_spacing_s`, gaps bounded by `max_gap_s` (None = no interpolated
      fillers: only real events), capped at `max_frames` (the render strategy's image
      budget: first + last + middle state refs);
    * `fps`: legacy one keyframe per second (t = 0..round(duration)).
    """

    mode: SamplingMode = "events"
    min_spacing_s: float = Field(default=1.0, gt=0.0)
    max_gap_s: float | None = Field(default=4.0, gt=0.0)
    max_frames: int = Field(default=6, ge=2)
    motion_threshold_x: float = Field(default=0.35, gt=0.0, le=1.0)
    grid_step_s: float = Field(default=0.25, gt=0.0, le=1.0)  # motion sampling grid

    @model_validator(mode="after")
    def _gap_fits_spacing(self) -> Self:
        if self.max_gap_s is not None and self.max_gap_s < 2 * self.min_spacing_s:
            raise ValueError("max_gap_s must be at least 2 x min_spacing_s")
        return self


# Analysis callers (plate spec, previz blocking) need every second.
DENSE: Final[SamplingCfg] = SamplingCfg(mode="fps")
# Production keyframes (S8 + video strategies): clip start/end + important events only
# (state changes, beat boundaries, contact, large-motion midpoints), no gap fillers.
KEYFRAME_SAMPLING: Final[SamplingCfg] = SamplingCfg(
    mode="events", max_gap_s=None, max_frames=5
)


@dataclass(frozen=True)
class Candidate:
    """One candidate keyframe time with why it matters."""

    t: float
    priority: int
    kind: EventKind | None
    label: str

    @property
    def rank(self) -> int:
        return KIND_RANK[self.kind] if self.kind else len(KIND_RANK)

    @property
    def is_endpoint(self) -> bool:
        return self.priority == ENDPOINT

    def relabel(self, label: str) -> Candidate:
        return replace(self, label=label)
