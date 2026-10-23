"""Typed contracts for the 1 fps keyframe planner (input from the graph, output plan).

`PlanInput` is everything the pure planner needs, already resolved from the StoryGraph by
`plan.graph_source`; `KeyframePlan` is the per-second visual state the renderer must draw.
Graph state is carried as `StateSnapshot`s: snapshot 0 is the clip's opening state and
snapshot `i + 1` the state after beat `i` (the last one equals the clip's closing state).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ScreenPos = Literal["left", "center", "right", "foreground", "background"]
ShotSize = Literal["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"]

# Left-to-right rank used by the continuity lint (depth planes sit at the centre column).
SCREEN_RANK: dict[str, int] = {
    "left": 0,
    "center": 1,
    "foreground": 1,
    "background": 1,
    "right": 2,
}


class CastInput(BaseModel):
    """One on-screen character with its resolved appearance and identity sheet."""

    entity_id: str
    name: str
    wardrobe: str
    description: str = ""
    appearance_id: str = ""
    ref_asset_id: str | None = None
    ref_uri: str | None = None
    position: ScreenPos = "center"


class ObjectInput(BaseModel):
    """One OBJECT entity that may appear in the clip (presence decided per second)."""

    entity_id: str
    name: str
    description: str = ""
    ref_asset_id: str | None = None
    ref_uri: str | None = None
    focus: bool = False


class BeatSpan(BaseModel):
    """One interaction step mapped onto the clip clock (seconds from clip start)."""

    index: int
    t_start: float
    t_end: float
    actor_id: str
    target_id: str | None = None
    action: str
    pre_state: str = ""
    post_state: str = ""


class StateSnapshot(BaseModel):
    """Graph state (`entity_id -> {attribute: value}`) at one story order."""

    order: int
    states: dict[str, dict[str, str]] = Field(default_factory=dict)


class CameraInput(BaseModel):
    shot_size: ShotSize = "MS"
    angle: str = "eye"
    movement: str = "static"
    lens_mm: int = 35


class PlanInput(BaseModel):
    """Graph-resolved inputs for one shot/clip."""

    project_id: str
    scene_id: str
    shot_id: str
    clip_index: int
    duration_s: float
    location_id: str
    location_name: str
    location_description: str = ""
    location_ref_asset_id: str | None = None
    location_ref_uri: str | None = None
    time_of_day: str = ""
    style: str = ""
    camera: CameraInput = Field(default_factory=CameraInput)
    cast: list[CastInput] = Field(default_factory=list)
    objects: list[ObjectInput] = Field(default_factory=list)
    beats: list[BeatSpan] = Field(default_factory=list)
    snapshots: list[StateSnapshot] = Field(default_factory=list)
    prompt_version_id: str = ""
    # Scene layout from the locked scene plate: entity id -> horizontal centre (0..1).
    layout: dict[str, float] = Field(default_factory=dict)
    # Character x at t=0 carried over from the previous clip's last keyframe (continuity).
    start_x: dict[str, float] = Field(default_factory=dict)


class CharacterKey(BaseModel):
    entity_id: str
    name: str
    wardrobe: str
    pose: str
    position: ScreenPos
    holding: list[str] = Field(default_factory=list)
    ref_asset_id: str | None = None
    x: float = 0.5  # horizontal centre in the frame (0 = left edge, 1 = right edge)


class ObjectKey(BaseModel):
    """An object alive at second `t`: exactly one instance, graph placement, visibility."""

    entity_id: str
    name: str
    placement: str
    holder_id: str | None = None
    visible: bool = True
    in_frame: bool = True
    count: int = 1
    x: float | None = None  # from the scene layout (set pieces / placed props)


class CameraKey(BaseModel):
    shot_size: ShotSize
    angle: str
    movement: str
    progress: float
    framing: str


class Keyframe(BaseModel):
    """Visual state at integer second `t` of the clip."""

    t: int
    beat_index: int
    phase: float
    snapshot_index: int
    characters: list[CharacterKey]
    objects: list[ObjectKey]
    setting: str
    camera: CameraKey
    delta: list[str] = Field(default_factory=list)


class KeyframePlan(BaseModel):
    project_id: str
    scene_id: str
    shot_id: str
    clip_index: int
    duration_s: float
    fps: int = 1
    prompt_version_id: str = ""
    plan_hash: str = ""
    keyframes: list[Keyframe] = Field(default_factory=list)

    def at(self, t: int) -> Keyframe:
        """Keyframe at second `t` (clamped to the plan)."""
        return self.keyframes[max(0, min(t, len(self.keyframes) - 1))]


class LintIssue(BaseModel):
    code: Literal[
        "object_count",
        "object_duplicate",
        "position_jump",
        "wardrobe_change",
        "timeline_open",
        "timeline_close",
        "scene_handoff",
    ]
    shot_id: str
    t: int
    entity_id: str
    message: str
