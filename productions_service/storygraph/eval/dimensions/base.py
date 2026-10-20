"""Dimension protocol, shared evaluation context and result helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ...qa.critic.checks import CriticThresholds, MediaSignals
from ...qa.critic.gate import check_flags
from ...qa.critic.severity import Severity, cites_timestamp
from ...qa.critic.spec import CriticSpec
from ...schema import QADefect
from ..contracts import DimensionName, DimensionResult, EvalInput, Evidence
from ..metrics.bundle import MetricBundle
from ..rubric import EvalRubric

VLM_CONFIDENCE = 0.7
_T_RE = re.compile(r"\bt\s*=\s*(\d+(?:\.\d+)?)")
_FLAG_ROUTES: tuple[tuple[DimensionName, tuple[str, ...]], ...] = (
    ("camera_adherence", ("framing", "camera", "angle", "shot_size", "zoom")),
    ("style_consistency", ("style",)),
    ("temporal_consistency", ("frozen", "bleed", "cut", "flicker", "morph")),
    ("character_consistency", ("character", "face", "identity", "design", "wardrobe")),
    ("spatial_consistency", ("axis", "overlap", "position", "mirror")),
    (
        "object_permanence",
        ("object", "prop", "duplicat", "vanish", "materializ", "missing"),
    ),
)


@dataclass(frozen=True)
class EvalContext:
    """Everything shared across dimensions for one clip (computed once by the engine)."""

    spec: CriticSpec
    rubric: EvalRubric
    metrics: MetricBundle
    signals: MediaSignals
    thr: CriticThresholds


class Dimension(Protocol):
    name: DimensionName

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult: ...


def concrete(evidence: str) -> Severity:
    """HIGH only for timestamped observations; otherwise MEDIUM."""
    return "high" if cites_timestamp(evidence) else "medium"


def first_time(text: str) -> float | None:
    """First `t=<s>` timestamp cited in `text`."""
    match = _T_RE.search(text or "")
    return float(match.group(1)) if match else None


def score_from_defects(defects: list[QADefect]) -> float:
    """1.0 minus severity-weighted penalties (HIGH 0.5, MEDIUM 0.2, LOW 0.05), floored at 0."""
    weights = {"high": 0.5, "medium": 0.2, "low": 0.05}
    return max(0.0, 1.0 - sum(weights[d.severity] for d in defects))


def flag_dimension(flag: str) -> DimensionName:
    """Dimension that owns a free-form critic/CV flag (physics is the fallback)."""
    low = flag.lower()
    for name, tokens in _FLAG_ROUTES:
        if any(tok in low for tok in tokens):
            return name
    return "physical_plausibility"


def routed_flags(ctx: EvalContext, name: DimensionName) -> list[QADefect]:
    """Critic drift flags + CV flags owned by dimension `name`."""
    flags = check_flags(ctx.rubric, ctx.signals)
    return [d for d in flags if flag_dimension(d.subject) == name]


def make_result(
    name: DimensionName,
    score: float,
    confidence: float,
    defects: list[QADefect],
    sub_scores: dict[str, float] | None = None,
    notes: list[Evidence] | None = None,
) -> DimensionResult:
    """Clamp scores and derive timestamped evidence from defects."""
    evidence = [Evidence(t_s=first_time(d.evidence), note=d.evidence) for d in defects]
    return DimensionResult(
        dimension=name,
        score=round(min(1.0, max(0.0, score)), 3),
        confidence=round(min(1.0, max(0.0, confidence)), 3),
        evidence=[*evidence, *(notes or [])],
        defects=defects,
        sub_scores=sub_scores or {},
    )
