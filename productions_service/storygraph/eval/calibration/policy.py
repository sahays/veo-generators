"""Fast, pure re-implementation of `eval.gate.decide` over pre-extracted clip features.

The threshold search evaluates thousands of gate configs; re-running `decide` (pydantic
objects, reason strings) for each is wasteful. `ClipFeatures` keeps only what the gate reads,
and `passes` mirrors `decide` exactly (asserted against `decide` in tests/eval).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...config import GateConfig
from ..contracts import EvalReport
from ..gate import demotable


@dataclass(frozen=True)
class ClipFeatures:
    """Gate inputs for one clip: per-dimension (score, confidence) and defect counts.

    `hard_high` counts the HIGH defects of `high` that demotion may not touch.
    """

    run_id: str
    shot_id: str
    scores: dict[str, tuple[float, float]]
    high: dict[str, int]
    medium: dict[str, int]
    hard_high: dict[str, int] = field(default_factory=dict)


def features(run_id: str, shot_id: str, report: EvalReport) -> ClipFeatures:
    """Extract gate features from an engine report."""
    res = report.results
    return ClipFeatures(
        run_id=run_id,
        shot_id=shot_id,
        scores={k: (r.score, r.confidence) for k, r in res.items()},
        high={k: sum(d.severity == "high" for d in r.defects) for k, r in res.items()},
        medium={
            k: sum(d.severity == "medium" for d in r.defects) for k, r in res.items()
        },
        hard_high={
            k: sum(d.severity == "high" and not demotable(d) for d in r.defects)
            for k, r in res.items()
        },
    )


def defect_counts(feat: ClipFeatures, cfg: GateConfig) -> tuple[int, int]:
    """(HIGH, MEDIUM) counts seen by the defect gate after per-dimension demotion."""
    high = medium = 0
    for dim, n in feat.high.items():
        hard = feat.hard_high.get(dim, 0)
        if cfg.for_dimension(dim).demote_high_defects:  # type: ignore[arg-type]
            high += hard
            medium += n - hard
        else:
            high += n
    return high, medium + sum(feat.medium.values())


def overall(feat: ClipFeatures, cfg: GateConfig) -> float:
    """Weight-normalized mean score (same rounding as `gate.overall_score`)."""
    pairs = [(cfg.for_dimension(d).weight, s) for d, (s, _c) in feat.scores.items()]  # type: ignore[arg-type]
    total = sum(w for w, _ in pairs)
    return round(sum(w * s for w, s in pairs) / total, 3) if total else 0.0


def _blocks(
    feat: ClipFeatures, dim: str, score: float, threshold: float, margin: float | None
) -> bool:
    if score >= threshold:
        return False
    if margin is None:
        return True
    evidence = feat.high.get(dim, 0) + feat.medium.get(dim, 0) > 0
    return evidence or score < threshold - margin


def hard_gate_failures(feat: ClipFeatures, cfg: GateConfig) -> list[str]:
    """Dimensions whose confident hard gate blocks (evidence-aware, same as `gate.decide`)."""
    out: list[str] = []
    for dim, (score, conf) in feat.scores.items():
        g = cfg.for_dimension(dim)  # type: ignore[arg-type]
        enforced = g.hard_gate and conf >= cfg.min_confidence
        if enforced and _blocks(feat, dim, score, g.threshold, g.evidence_margin):
            out.append(dim)
    return out


def passes(feat: ClipFeatures, cfg: GateConfig) -> bool:
    """True iff `decide` would approve the clip under `cfg`."""
    high, medium = defect_counts(feat, cfg)
    if high or medium > cfg.max_medium_defects:
        return False
    if hard_gate_failures(feat, cfg):
        return False
    return overall(feat, cfg) >= cfg.overall_threshold
