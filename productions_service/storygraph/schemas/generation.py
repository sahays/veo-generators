"""Layer 5 — generation runs, QA reports and Omni prompt versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .base import NodeBase, Role, _utc_now

PromptFormat = Literal[
    "json", "hybrid"
]  # text sent to Omni: legacy spec JSON | V3 hybrid

# ─────────────────────────────────────────────────────────────────────────────
# Layer 5 — Generation & QA
# ─────────────────────────────────────────────────────────────────────────────


class QADefect(BaseModel):
    """One observed clip defect; `likely_cause` routes repair (spec vs render vs reference)."""

    type: str
    severity: Literal["high", "medium", "low"]
    subject: str = ""
    evidence: str
    likely_cause: Literal["spec", "render", "reference"] = "render"


class DimensionScore(BaseModel):
    """One named eval dimension's score/confidence and whether it cleared its gate."""

    dimension: str
    score: float
    confidence: float
    threshold: float = 0.0
    hard_gate: bool = False
    passed: bool = True


class QAReport(BaseModel):
    face_similarity: dict[str, float] = Field(default_factory=dict)
    wardrobe_match: float = 1.0
    setting_match: float = 1.0
    action_achieved: float = 1.0
    physics_plausibility: float = 1.0
    object_permanence: float = 1.0
    continuity_prev_shot: float = 1.0
    dialogue_wer: float = 0.0
    artifact_flags: list[str] = Field(default_factory=list)
    passed: bool = True
    failure_reasons: list[str] = Field(default_factory=list)
    suggested_fix: Literal[
        "none", "retry_seed", "recompile_prompt", "resplit_shot", "redesign_asset"
    ] = "none"
    # Phase 3 spec-aware critic outputs (append-only).
    defects: list[QADefect] = Field(default_factory=list)
    identity_scores: dict[str, float] = Field(default_factory=dict)
    steps_done: dict[str, bool] = Field(default_factory=dict)
    camera_match: float = 1.0
    hard_cut_times_s: list[float] = Field(default_factory=list)
    frames_sampled: int = 0
    rubric_version: str = ""
    # Video-eval engine outputs (append-only).
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    eval_overall: float | None = None


class ClipTrim(BaseModel):
    """Tail trim applied before storage because of a late hard cut (seconds)."""

    original_duration_s: float
    duration_s: float
    cut_at_s: float


class GenerationRun(NodeBase):
    node_type: Literal["GenerationRun"] = "GenerationRun"
    shot_id: str
    attempt: int
    provider: str
    model: str
    compiled_prompt: str
    negative_prompt: str = ""
    reference_asset_ids: list[str] = Field(default_factory=list)
    first_frame_asset_id: str | None = None
    seed: int
    package_hash: str
    output_video_uri: str | None = None
    output_video_signed_url: str | None = None
    extracted_last_frame_asset_id: str | None = None
    qa_scores: QAReport | None = None
    render_fallback: dict[str, Any] | None = None
    shot_content_hash: str | None = None  # Shot.content_hash at render time
    clip_trim: ClipTrim | None = None  # set when a late hard cut was trimmed off
    prompt_version_id: str | None = None  # PromptVersion the clip was rendered from
    # `compiled_prompt` is the exact text sent; the critic reads expectations from the spec.
    spec_json: str | None = None  # OmniClipSpec JSON the prompt was rendered from
    prompt_format: PromptFormat | None = (
        None  # None = legacy run (prompt was spec JSON)
    )


# ── Omni prompt versioning (one immutable row per distinct compiled spec) ────────

PromptVersionAuthor = Literal["compiler", "prompt_doctor", "human"]
PromptVersionStatus = Literal["active", "superseded", "reverted", "rejected"]


class PatchOp(BaseModel):
    """RFC 6902-style JSON patch op describing how a spec differs from its parent."""

    op: Literal["add", "replace", "remove"]
    path: str
    value: Any = None


class PromptVersion(NodeBase):
    """One compiled `OmniClipSpec` JSON sent (or queued) to Omni for a shot.

    `spec_json`/`spec_hash` are immutable; only status and eval results evolve.
    """

    node_type: Literal["PromptVersion"] = "PromptVersion"
    created_by: Role = Role.PIPELINE
    status: PromptVersionStatus = "active"  # type: ignore[assignment]
    shot_id: str
    parent_id: str | None = None
    spec_json: str
    spec_hash: str
    author: PromptVersionAuthor = "compiler"
    patch: list[PatchOp] | None = None
    reason: str = ""
    eval_score: float | None = None
    eval_summary: dict[str, Any] | None = None
    run_ids: list[str] = Field(default_factory=list)
    shot_content_hash: str | None = None  # Shot.content_hash the spec was authored for
    created_at: datetime = Field(default_factory=_utc_now)
    # Derived view of `spec_json` actually sent to Omni (refreshed if the format changes).
    rendered_prompt: str | None = None
    prompt_format: PromptFormat | None = None
