"""Typed HTTP contract for the S8_KEYFRAMES strip (`/api/v1/productions/{pid}/…/keyframes`).

Mirrored 1:1 by `frontend/src/lib/api/keyframes.ts`. Routes:

* GET  /api/v1/productions/{pid}/keyframes                          -> KeyframeBoardResponse
* GET  /api/v1/productions/{pid}/shots/{shot_id}/keyframes          -> KeyframeStripResponse
* POST /api/v1/productions/{pid}/shots/{shot_id}/keyframes/{t}/regenerate
       body RegenerateKeyframePayload                               -> KeyframeStripResponse
  (re-derives frames t..N of that clip as a new KeyframeSet version; if t == N the next clip
  of the scene re-derives from the new shared frame; the shot's render becomes stale)
* Stage regenerate: POST /api/v1/productions/{pid}/stages/S8_KEYFRAMES/run?force=true
  (existing route; cascades S8_KEYFRAMES -> S8_RENDER -> S9_QA -> S10_ASSEMBLE)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FrameStatus = Literal["approved", "needs_review", "manual_edit"]
SetStatus = Literal["active", "superseded"]


class KeyframeFrameView(BaseModel):
    t: int
    asset_id: str
    url: str  # signed (or gs://) URL of the PNG
    status: FrameStatus
    attempts: int
    issues: list[str] = Field(default_factory=list)
    shared_from: str | None = (
        None  # "<shot_id>@t<N>" when this is the previous clip's last frame
    )
    edited_by: Literal["pipeline", "human"] = "pipeline"
    state_summary: str = ""  # graph state at t: who does what / holds what
    drift: dict[str, float] = Field(default_factory=dict)  # vs the locked scene plate


class KeyframeSetVersionView(BaseModel):
    set_id: str
    version: int
    status: SetStatus
    created_at: str
    reason: str = ""


class KeyframeStripResponse(BaseModel):
    shot_id: str
    scene_id: str
    clip_index: int
    set_id: str | None = None
    version: int = 0
    plan_hash: str = ""
    needs_manual_edit: bool = False
    stale: bool = False  # graph changed since this set was derived
    failure_reason: str = ""  # derivation failed: no frames, shot blocked until re-run
    frames: list[KeyframeFrameView] = Field(default_factory=list)
    versions: list[KeyframeSetVersionView] = Field(default_factory=list)


class KeyframeBoardResponse(BaseModel):
    project_id: str
    strategy: str  # active video.render_strategy
    shots: list[KeyframeStripResponse] = Field(default_factory=list)


class RegenerateKeyframePayload(BaseModel):
    instruction: str = Field(
        default="", max_length=600
    )  # optional human edit instruction
