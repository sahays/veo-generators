"""Layer-4 clip & look models: screenwriter-owned `ClipScript`, director-owned `ShotLook`.

These models carry no dependency on `storygraph.schema` so `schema.py` can re-export them.
"""

from __future__ import annotations

import math
from typing import Final

from pydantic import BaseModel, Field, field_validator

CLIP_MIN_S: Final[float] = 8.0
CLIP_MAX_S: Final[float] = 10.0
MAX_CLIP_STEPS: Final[int] = 3
MAX_CLIP_WORDS: Final[int] = 22


def clamp_clip_duration(value: float | str | None) -> float:
    """Deterministically clamp any raw duration into the Omni clip window [8.0, 10.0]s."""
    try:
        num = float(value) if value is not None else CLIP_MIN_S
    except (TypeError, ValueError):
        num = CLIP_MIN_S
    if math.isnan(num):
        num = CLIP_MIN_S
    return round(max(CLIP_MIN_S, min(CLIP_MAX_S, num)), 1)


class ClipScript(BaseModel):
    """One self-contained 8–10s Omni generation unit authored by the Screenwriter."""

    clip_index: int
    duration_s: float = CLIP_MIN_S
    omni_prompt: str = ""
    step_indices: list[int] = Field(default_factory=list)
    dialogue_line_ids: list[str] = Field(default_factory=list)
    opening_state: str = ""
    closing_state: str = ""

    @field_validator("duration_s", mode="before")
    @classmethod
    def _clamp_duration(cls, value: float | str | None) -> float:
        return clamp_clip_duration(value)


class LightingSpec(BaseModel):
    key: str = ""
    fill: str = ""
    practicals: str = ""
    direction: str = ""
    quality: str = ""


class ColorGradeSpec(BaseModel):
    shades: list[str] = Field(default_factory=list)
    contrast: str = ""
    saturation: str = ""
    temperature: str = ""


class ShotLook(BaseModel):
    """Per-shot cinematography look authored by the Director within StyleGuide limits."""

    lighting: LightingSpec = Field(default_factory=LightingSpec)
    color_grade: ColorGradeSpec = Field(default_factory=ColorGradeSpec)
    mood: str = ""
    composition: str = ""
    camera_motion_intent: str = ""
