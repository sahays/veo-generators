"""Eval gate: defect gate (any HIGH / > max MEDIUM) + per-dimension hard gates + weighted overall.

Thresholds come from `GateConfig` only (identical on every attempt). A hard gate is enforced
only when the dimension's confidence reaches `min_confidence`, so an unmeasurable dimension
cannot block on its own — its typed defects still go through the defect gate. Dimensions with
`demote_high_defects` (golden-set calibration, docs/eval/eval_calibration_v1.md) feed their
HIGH defects to the defect gate as MEDIUM.
"""

from __future__ import annotations

from dataclasses import replace

from ..qa.critic.checks import CriticThresholds
from ..qa.critic.gate import GateDecision, gate
from ..schema import DimensionScore, QADefect
from .contracts import DimensionResult, GateConfig


def overall_score(results: dict[str, DimensionResult], cfg: GateConfig) -> float:
    """Weight-normalized mean of dimension scores (0.0 with no weighted dimensions)."""
    pairs = [(cfg.for_dimension(r.dimension).weight, r.score) for r in results.values()]
    total = sum(w for w, _ in pairs)
    return round(sum(w * s for w, s in pairs) / total, 3) if total else 0.0


def dimension_scores(
    results: dict[str, DimensionResult], cfg: GateConfig
) -> list[DimensionScore]:
    """Per-dimension gate outcome (passed unless a confident hard gate is below threshold)."""
    out: list[DimensionScore] = []
    for r in results.values():
        g = cfg.for_dimension(r.dimension)
        enforced = g.hard_gate and r.confidence >= cfg.min_confidence
        out.append(
            DimensionScore(
                dimension=r.dimension,
                score=r.score,
                confidence=r.confidence,
                threshold=g.threshold,
                hard_gate=g.hard_gate,
                passed=not enforced or r.score >= g.threshold,
            )
        )
    return out


def gating_defects(
    results: dict[str, DimensionResult], cfg: GateConfig
) -> list[QADefect]:
    """Every defect, with HIGH demoted to MEDIUM for dimensions configured to demote."""
    out: list[QADefect] = []
    for r in results.values():
        demote = cfg.for_dimension(r.dimension).demote_high_defects
        for d in r.defects:
            high = demote and d.severity == "high"
            out.append(d.model_copy(update={"severity": "medium"}) if high else d)
    return out


def decide(
    results: dict[str, DimensionResult],
    cfg: GateConfig,
    thr: CriticThresholds,
) -> tuple[GateDecision, list[DimensionScore], float]:
    """Combine the defect gate, hard-gated dimensions and the overall threshold."""
    defects = gating_defects(results, cfg)
    base = gate(defects, replace(thr, max_medium_defects=cfg.max_medium_defects))
    scores = dimension_scores(results, cfg)
    overall = overall_score(results, cfg)
    reasons = list(base.failure_reasons)
    reasons += [
        f"{s.dimension} {s.score:.2f} below {s.threshold:.2f} (hard gate)"
        for s in scores
        if not s.passed
    ]
    if overall < cfg.overall_threshold:
        reasons.append(f"overall {overall:.2f} below {cfg.overall_threshold:.2f}")
    if not reasons:
        return base, scores, overall
    fix = base.suggested_fix if base.suggested_fix != "none" else "retry_seed"
    decision = GateDecision(False, reasons, fix, base.artifact_flags)
    return decision, scores, overall
