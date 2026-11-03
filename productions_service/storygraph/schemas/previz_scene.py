"""Typed previz contract: location layout (3D set), camera rig, per-clip blocking, render input.

World frame (metres, right-handed, Blender convention): +X screen right, +Y away from the
master camera (depth), +Z up; the floor is Z=0 and the room spans X in [-W/2, W/2],
Y in [0, D]. The master camera sits at Y<0 looking along +Y, exactly the camera the scene
plate was drawn from, so plate-space x (0..1 of the frame width) maps to world X by
`previz.blocking.project`. Plain data only: the Blender script just reads it.

v2 (schema_version 2, all additions optional so v1 scenes still load):
* `SetPiece.kind` + `params`: parametric primitives (cabinet with drawers, chest with lid,
  bench with legs, shelf unit, stool, door, window, toolbox, table) instead of plain boxes;
* `CharacterTrack.archetype`: silhouette + procedural walk/reach/push per body type;
* `CameraRig.sensor_width_mm` / `shift_x` / `shift_y`: a camera calibrated to the plate;
* `PrevizScene.projection`: the plate image camera-projected onto walls, floor and set
  pieces from the calibrated master camera (the previz looks like the real room);
* `RenderSettings.passes`: per-object ID masks and depth written next to the MP4.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PREVIZ_SCHEMA_VERSION = 2
Shape = Literal["box", "cylinder"]
Pose = Literal["stand", "walk", "reach", "crouch", "sit", "point", "push"]
PieceKind = Literal[
    "box", "cylinder", "cabinet", "chest", "bench", "table", "shelf", "stool", "door",
    "window", "toolbox",
]  # fmt: skip
Archetype = Literal["human", "small_robot", "quadruped", "creature"]
RenderPass = Literal["object_id", "depth"]
HexColor = str  # "#rrggbb"


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Room(BaseModel):
    width: float = 8.0
    depth: float = 6.0
    height: float = 3.0
    floor_color: HexColor = "#b08060"
    wall_color: HexColor = "#d8cfc4"


class SetPiece(BaseModel):
    """Static furniture/fixture standing on the floor (or mounted on a wall: door/window).

    `kind` selects a parametric primitive built inside `size`; `params` are optional
    kind-specific numbers (e.g. cabinet `drawers`, bench `leg_inset`, shelf `shelves`,
    window `sill_z`). Unknown kinds/params fall back to a box of `size`."""

    entity_id: str
    name: str
    shape: Shape = "box"
    kind: PieceKind = "box"
    params: dict[str, float] = Field(default_factory=dict)
    position: Vec3  # centre of the footprint on the floor (z = 0)
    size: Vec3  # width (X), depth (Y), height (Z)
    rotation_z_deg: float = 0.0
    color: HexColor = "#888888"


class LocationLayout(BaseModel):
    """One location's 3D set, shared by every scene there (versioned + cached)."""

    location_id: str
    name: str
    room: Room = Field(default_factory=Room)
    set_pieces: list[SetPiece] = Field(default_factory=list)
    source_hash: str = ""  # hash of the inputs it was estimated from (cache key)


class CameraRig(BaseModel):
    """Shot camera: start/end pose (end == start for static shots).

    `sensor_width_mm` with `lens_mm` fixes the horizontal FOV (sensor fit HORIZONTAL);
    `shift_x` / `shift_y` are Blender lens shifts (fraction of the larger sensor side)."""

    position: Vec3
    target: Vec3
    end_position: Vec3 | None = None
    end_target: Vec3 | None = None
    lens_mm: float = 35.0
    sensor_width_mm: float = 36.0
    shift_x: float = 0.0
    shift_y: float = 0.0
    roll_deg: float = 0.0


class ProjectionSpec(BaseModel):
    """Camera-project `image_file` (relative to layout.json) onto room + set pieces."""

    image_file: str
    camera: CameraRig  # the calibrated master camera the image was drawn from
    strength: float = 1.0  # 1 = projected texture only, 0 = flat greybox colours


class CharacterKey(BaseModel):
    t: float
    position: Vec3  # feet on the floor
    facing_deg: float = 0.0  # 0 = facing the camera (-Y), 90 = facing screen right (+X)
    pose: Pose = "stand"
    holding: str | None = None


class CharacterTrack(BaseModel):
    entity_id: str
    name: str
    color: HexColor
    height_m: float = 1.6
    archetype: Archetype = "human"
    keys: list[CharacterKey] = Field(default_factory=list)


class PropKey(BaseModel):
    t: float
    position: Vec3
    holder_id: str | None = None  # attached to this character's hand while set
    visible: bool = True


class PropTrack(BaseModel):
    entity_id: str
    name: str
    color: HexColor
    kind: PieceKind = "box"
    params: dict[str, float] = Field(default_factory=dict)
    size: Vec3 = Field(default_factory=lambda: Vec3(x=0.25, y=0.25, z=0.25))
    keys: list[PropKey] = Field(default_factory=list)


class BlockingTrack(BaseModel):
    shot_id: str
    scene_id: str
    clip_index: int
    duration_s: float
    characters: list[CharacterTrack] = Field(default_factory=list)
    props: list[PropTrack] = Field(default_factory=list)


class RenderSettings(BaseModel):
    width: int = 480
    height: int = 270
    fps: int = 24
    engine: Literal["BLENDER_WORKBENCH", "BLENDER_EEVEE_NEXT", "CYCLES"] = (
        "BLENDER_WORKBENCH"
    )
    samples: int = 8
    # Extra per-frame outputs next to the MP4: `passes/object_id/%04d.png` (each entity a
    # flat colour from `passes/ids.json`) and `passes/depth/%04d.png` (16-bit metres*1000).
    passes: list[RenderPass] = Field(default_factory=list)
    pass_fps: int = 1  # pass frames per second (1 = one per keyframe second)


class PrevizScene(BaseModel):
    """Exactly what `render/build_scene.py` consumes (written as layout.json)."""

    schema_version: int = PREVIZ_SCHEMA_VERSION
    layout: LocationLayout
    camera: CameraRig
    blocking: BlockingTrack
    render: RenderSettings = Field(default_factory=RenderSettings)
    projection: ProjectionSpec | None = None
