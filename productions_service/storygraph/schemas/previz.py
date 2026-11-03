"""Layer-5 previz nodes (optional S8_PREVIZ): versioned location layouts and per-shot records.

* `PrevizLayout` (`previz_layouts`): one active version per LOCATION (ids `pzl_<loc>_<n>`),
  older ones superseded — re-estimated only when its inputs (`layout.source_hash`) change.
* `PrevizShot` (`previz_shots`): one active version per shot (ids `pzs_<shot>_<n>`): the
  greybox render, its typed failure reason, and the restyle variants with their outputs.
Media live in GCS as `Asset`s; these documents carry URIs only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .base import NodeBase
from .previz_scene import LocationLayout

PrevizVersionStatus = Literal["active", "superseded"]
PrevizShotStatus = Literal["pending", "running", "done", "failed"]
PrevizVariantId = Literal["E1_omni_restyle", "E2_keyframe_restyle"]
PrevizRunVariant = Literal[
    "previz_only", "E1_omni_restyle", "E2_keyframe_restyle", "both"
]


class PrevizLayout(NodeBase):
    node_type: Literal["PrevizLayout"] = "PrevizLayout"
    location_id: str
    set_status: PrevizVersionStatus = "superseded"
    layout: LocationLayout
    thumbnail_uri: str | None = None
    issues: list[str] = Field(default_factory=list)


class PrevizVariantRecord(BaseModel):
    variant: PrevizVariantId
    status: PrevizShotStatus = "pending"
    video_uri: str | None = None
    frame_uris: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    promoted: bool = False
    generation_run_id: str | None = None  # set by promote
    model: str = ""
    prompt: str = ""
    seconds: float | None = None


class PrevizShot(NodeBase):
    node_type: Literal["PrevizShot"] = "PrevizShot"
    shot_id: str
    scene_id: str
    clip_index: int
    set_status: PrevizVersionStatus = "superseded"
    previz_status: PrevizShotStatus = "pending"
    layout_id: str | None = None
    scene_hash: str = ""  # hash of the PrevizScene JSON rendered (reuse key)
    scene_json_uri: str | None = None
    previz_video_uri: str | None = None
    render_seconds: float | None = None
    blender_version: str | None = None
    failure_reason: str | None = None
    variants: list[PrevizVariantRecord] = Field(default_factory=list)
    parent_id: str | None = None


PrevizRunStatus = Literal["running", "approved", "failed"]


class PrevizRun(NodeBase):
    """Live status of one background S8_PREVIZ request (`previz_runs`, id `pzr_<ts>`)."""

    node_type: Literal["PrevizRun"] = "PrevizRun"
    variant: PrevizRunVariant = "previz_only"
    scene_ids: list[str] | None = None
    force: bool = False
    run_status: PrevizRunStatus = "running"
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    shots_done: int = 0
    shots_failed: int = 0
