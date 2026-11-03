"""Typed HTTP contract for the Blender previz tab (`/api/v1/productions/{pid}/previz…`).

Mirrored 1:1 by the frontend previz types. Routes:

* GET  /api/v1/productions/{pid}/previz                         -> PrevizBoardResponse
* POST /api/v1/productions/{pid}/previz/run   body PrevizRunPayload -> PrevizRunAccepted
  (returns immediately; S8_PREVIZ runs in the background, outside the main cascade)
* POST /api/v1/productions/{pid}/previz/shots/{shot_id}/promote
       body PromotePrevizPayload                                -> ShotPreviz
  (creates a GenerationRun `previz_<variant>` and makes it the shot's active render)
Only URLs of media that actually exist are returned (signed); otherwise null / [].
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PrevizStatus = Literal["pending", "running", "done", "failed"]
StageRunStatus = Literal["idle", "running", "approved", "failed"]
VariantName = Literal["E1_omni_restyle", "E2_keyframe_restyle"]
RunVariant = Literal["previz_only", "E1_omni_restyle", "E2_keyframe_restyle", "both"]
ID_PATTERN = r"^[A-Za-z0-9_\-]{1,120}$"
# OWASP A03: ids are restricted to a safe alphabet before they reach any store query.
SafeId = Annotated[str, StringConstraints(pattern=ID_PATTERN)]


class PrevizStageRunView(BaseModel):
    status: StageRunStatus = "idle"
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class PrevizLayoutView(BaseModel):
    location_id: str
    name: str
    version: int
    thumbnail_url: str | None = None


class PrevizVariantView(BaseModel):
    variant: VariantName
    status: PrevizStatus
    video_url: str | None = None
    frame_urls: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    promoted: bool = False


class ShotPreviz(BaseModel):
    shot_id: str
    scene_id: str
    clip_index: int
    status: PrevizStatus = "pending"
    failure_reason: str | None = None
    previz_video_url: str | None = None
    render_seconds: float | None = None
    variants: list[PrevizVariantView] = Field(default_factory=list)


class PrevizBoardResponse(BaseModel):
    project_id: str
    blender_version: str | None = None
    stage_run: PrevizStageRunView | None = None
    layouts: list[PrevizLayoutView] = Field(default_factory=list)
    shots: list[ShotPreviz] = Field(default_factory=list)


class PrevizRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: RunVariant = "previz_only"
    scene_ids: list[SafeId] | None = Field(default=None, max_length=200)
    force: bool = False


class PrevizRunAccepted(BaseModel):
    accepted: bool = True
    stage_run_id: str


class PromotePrevizPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: VariantName
