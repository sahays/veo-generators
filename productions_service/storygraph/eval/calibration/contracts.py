"""Typed contracts for golden-set calibration: score jobs, cached engine scores, golden labels.

The three stages exchange only these models (as JSONL), so scoring (network, slow), agreement
analysis and threshold search (pure, fast) can run independently and be re-run from cache.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..contracts import EvalReport

Target = Literal["kids", "strict"]


class RefImage(BaseModel):
    """One labelled reference image on local disk (identity sheet or location plate)."""

    label: str
    kind: Literal["identity", "setting", "style"] = "identity"
    entity_names: list[str] = Field(default_factory=list)
    path: str


class ScoreJob(BaseModel):
    """Everything needed to re-score one golden clip with the eval engine."""

    run_id: str
    shot_id: str
    clip_path: str
    spec_json: str
    refs: list[RefImage] = Field(default_factory=list)
    prev_clip_path: str | None = None
    style_guide: str = ""


class CachedScore(BaseModel):
    """Engine output for one clip (raw report, so any gate config can be re-applied offline)."""

    run_id: str
    shot_id: str
    report: EvalReport | None = None
    error: str = ""
    engine_version: str = ""
    scored_at: str = ""


class GoldenDimension(BaseModel):
    """Golden 1-5 score, pass flag and defect tags for one dimension of one clip."""

    score: int = Field(ge=1, le=5)
    passed: bool
    na: bool = False
    tags: list[str] = Field(default_factory=list)
    severities: list[str] = Field(default_factory=list)


class GoldenLabel(BaseModel):
    """Golden verdicts for one clip (agent-labelled, pending human review)."""

    run_id: str
    shot_id: str
    overall_pass: bool
    kids_ok: bool
    borderline: bool = False
    dims: dict[str, GoldenDimension] = Field(default_factory=dict)

    def target(self, which: Target) -> bool:
        """Golden positive class for `which` target (kids-draft acceptable or strict pass)."""
        return self.kids_ok if which == "kids" else self.overall_pass


class BinaryMetrics(BaseModel):
    """Pass-class confusion counts plus precision / recall / F1 / accuracy."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        """Share of engine passes the golden set also passes (1.0 when nothing passes)."""
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        """Share of golden passes the engine also passes."""
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall (0.0 without true positives)."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if self.tp else 0.0

    @property
    def accuracy(self) -> float:
        """Share of clips where engine and golden agree."""
        n = self.tp + self.fp + self.fn + self.tn
        return (self.tp + self.tn) / n if n else 0.0

    def summary(self) -> dict[str, float | int]:
        """Flat, rounded view for reports and JSON output."""
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "accuracy": round(self.accuracy, 3),
        }
