"""Typed records exchanged between the keyframe experiment stages (render -> judge -> report)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VariantId = Literal[
    "A_direct", "B_interp", "C_animatic", "D1_anchored", "D2_anchored_text"
]
StrategyId = Literal[
    "direct",
    "keyframe_interp",
    "animatic_edit",
    "keyframe_anchored",
    "keyframe_anchored_text",
]
STRATEGY_OF: dict[str, StrategyId] = {
    "A_direct": "direct",
    "B_interp": "keyframe_interp",
    "C_animatic": "animatic_edit",
    "D1_anchored": "keyframe_anchored",
    "D2_anchored_text": "keyframe_anchored_text",
}


class RenderRecord(BaseModel):
    shot_id: str
    variant: VariantId
    sample: int
    clip_path: str | None
    ok: bool
    latency_s: float
    omni_calls: int
    error: str = ""


class ObjectCount(BaseModel):
    name: str
    count: int = Field(ge=0)


class CharacterObs(BaseModel):
    name: str
    present: bool
    outfit_matches: bool


class FrameObs(BaseModel):
    index: int
    objects: list[ObjectCount] = Field(default_factory=list)
    characters: list[CharacterObs] = Field(default_factory=list)
    extra_characters: int = Field(default=0, ge=0)


class ClipObservation(BaseModel):
    """VLM answer for one clip: per-frame counts + beat adherence."""

    frames: list[FrameObs] = Field(default_factory=list)
    beats_done: list[bool] = Field(default_factory=list)


class ContinuityObs(BaseModel):
    same_characters_and_outfits: bool
    same_objects_and_layout: bool
    score: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)


class ClipMetrics(BaseModel):
    shot_id: str
    variant: VariantId
    sample: int
    frames: int
    chest_dup_rate: float
    chest_present_rate: float
    cabinet_present_rate: float
    cabinet_flicker: int
    outfit_stability: float
    identity_presence: float
    extra_char_rate: float
    action_adherence: float
    cuts: int
    eval_overall: float | None = None
    eval_gate: bool | None = None
    eval_dims: dict[str, float] = Field(default_factory=dict)
