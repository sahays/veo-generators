"""Layer-5 keyframe nodes: one immutable `KeyframeSet` version per shot (S8_KEYFRAMES).

Versioned like `PromptVersion`: ids `kfs_<shot>_<n>`, exactly one `active` set per shot, older
ones `superseded`. A set records the 1 fps frames t = 0..N of the shot's clip. Frame 0 of
clip k+1 is the *same asset* as frame N of clip k in the scene (`shared_from`), so continuity
between clips is exact. Images live in GCS (`Asset(kind="keyframe")`); the set lives in
Firestore (`keyframe_sets`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .base import NodeBase

KeyframeFrameStatus = Literal["approved", "needs_review", "manual_edit"]
KeyframeSetStatus = Literal["active", "superseded"]
KeyframeAuthor = Literal["pipeline", "human"]


class KeyframeFrame(BaseModel):
    """One keyframe second of a shot."""

    t: int
    asset_id: str
    uri: str
    status: KeyframeFrameStatus = "approved"
    attempts: int = 0
    issues: list[str] = Field(default_factory=list)
    shared_from: str | None = None  # "<shot_id>@t<N>" (previous clip's last frame)
    edited_by: KeyframeAuthor = "pipeline"
    state_summary: str = ""


class KeyframeSet(NodeBase):
    node_type: Literal["KeyframeSet"] = "KeyframeSet"
    shot_id: str
    scene_id: str
    clip_index: int
    set_status: KeyframeSetStatus = "superseded"
    plan_hash: str
    shot_content_hash: str | None = None
    prompt_version_id: str = ""
    duration_s: float
    frames: list[KeyframeFrame] = Field(default_factory=list)
    needs_manual_edit: bool = False
    reason: str = ""
    parent_id: str | None = None

    @property
    def last(self) -> KeyframeFrame:
        return self.frames[-1]
