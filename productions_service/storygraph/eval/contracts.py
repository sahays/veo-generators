"""Typed data contracts shared by the eval engine, the S9 critic and the offline harness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..config import DimensionGate, DimensionName, GateConfig
from ..omni.spec import OmniClipSpec
from ..schema import QADefect

EVAL_VERSION = "video-eval-v1"


class Evidence(BaseModel):
    """One observed fact pinned to a clip time (`t_s=None` for whole-clip measurements)."""

    t_s: float | None = None
    note: str


class DimensionResult(BaseModel):
    """Outcome of one named dimension: score/confidence in [0, 1] plus typed defects."""

    dimension: DimensionName
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    defects: list[QADefect] = Field(default_factory=list)
    sub_scores: dict[str, float] = Field(default_factory=dict)


class EvalReport(BaseModel):
    """All dimension results for one clip, the weighted overall score and engine version."""

    results: dict[str, DimensionResult] = Field(default_factory=dict)
    overall: float = 0.0
    version: str = EVAL_VERSION
    duration_s: float = 0.0
    cut_times_s: list[float] = Field(default_factory=list)
    frames_sampled: int = 0
    rubric_version: str = ""

    def defects(self) -> list[QADefect]:
        """Every defect across dimensions in a stable (dimension-declaration) order."""
        return [d for r in self.results.values() for d in r.defects]


class LabelledRef(BaseModel):
    """A labelled reference image (identity / setting ground truth; never part of the clip)."""

    label: str
    kind: Literal["identity", "setting", "style"] = "identity"
    entity_names: list[str] = Field(default_factory=list)
    png: bytes


class EvalInput(BaseModel):
    """Everything the engine may judge for one clip (and nothing outside it)."""

    clip_bytes: bytes = b""
    clip_path: str | None = None
    spec_json: str
    refs: list[LabelledRef] = Field(default_factory=list)
    prev_last_frame: bytes | None = None
    prev_clip_bytes: bytes | None = None
    style_guide: str = ""
    shot_id: str = ""

    def load_clip(self) -> bytes:
        """Clip bytes from memory or from `clip_path` (empty when neither is available)."""
        if self.clip_bytes or not self.clip_path:
            return self.clip_bytes
        path = Path(self.clip_path)
        return path.read_bytes() if path.is_file() else b""

    def omni_spec(self) -> OmniClipSpec | None:
        """Strictly typed spec when the prompt is a current OmniClipSpec, else None."""
        try:
            return OmniClipSpec.model_validate_json(self.spec_json)
        except (ValidationError, ValueError):
            return None

    def spec_dict(self) -> dict[str, Any]:
        """Defensive dict view of the spec (works for legacy / partially valid prompts)."""
        try:
            data = json.loads(self.spec_json or "{}")
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


__all__ = [
    "EVAL_VERSION",
    "DimensionGate",
    "DimensionName",
    "DimensionResult",
    "EvalInput",
    "EvalReport",
    "Evidence",
    "GateConfig",
    "LabelledRef",
]
