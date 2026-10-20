"""Temporal consistency: hard cuts, freezes, flicker, jumps, morphing, duration vs requested."""

from __future__ import annotations

from ...qa.critic.checks import check_cuts, defect
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput
from ..metrics.video import VideoMetrics
from .base import EvalContext, concrete, make_result, routed_flags

DURATION_TOLERANCE = 0.25
MIN_FLICKERS = 2
# Freeze/flicker are MEDIUM defects: they lower the score but stay above the default hard-gate
# threshold, so only an early hard cut or morphing hard-fails temporal on its own.
FREEZE_SCORE = 0.65
FLICKER_SCORE = 0.65
_CUT_SCORE = {"medium": 0.4, "low": 0.8, "high": 0.2}


def _metric_defects(v: VideoMetrics) -> tuple[list[QADefect], float]:
    """Deterministic temporal defects and the lowest score they imply."""
    defects: list[QADefect] = []
    caps = [1.0]
    for start, end in v.freeze_spans:
        msg = f"frames identical t={start:.2f}s-{end:.2f}s"
        defects.append(defect("frozen_frame", "medium", "clip", msg))
        caps.append(FREEZE_SCORE)
    if len(v.flicker_times) >= MIN_FLICKERS:
        stamps = ", ".join(f"t={t:.2f}s" for t in v.flicker_times[:4])
        defects.append(
            defect("flicker", "medium", "clip", f"A-B-A flicker at {stamps}")
        )
        caps.append(0.6)
    for t in v.jump_times:
        defects.append(
            defect("pose_jump", "low", "clip", f"abrupt change at t={t:.2f}s")
        )
    caps.append(max(0.6, 1.0 - 0.1 * len(v.jump_times)))
    if abs(v.duration_ratio - 1.0) > DURATION_TOLERANCE:
        msg = f"duration {v.duration_s:.2f}s vs requested {v.requested_s:.2f}s"
        defects.append(defect("duration_mismatch", "low", "clip", msg))
        caps.append(0.8)
    return defects, min(caps)


class TemporalConsistency:
    name = "temporal_consistency"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        cut_defects, _cuts = check_cuts(ctx.spec, ctx.rubric, ctx.signals, ctx.thr)
        metric_defects, score = _metric_defects(ctx.metrics.video)
        score = min([score, *(_CUT_SCORE[d.severity] for d in cut_defects)])
        morph: list[QADefect] = []
        if ctx.rubric.temporal.morphing_seen:
            ev = ctx.rubric.temporal.evidence
            morph = [
                defect("morphing", concrete(ev), "clip", ev or "morphing observed")
            ]
            score = min(score, 0.4)
        defects = [*cut_defects, *metric_defects, *morph]
        defects += routed_flags(ctx, "temporal_consistency")
        confidence = 0.9 if ctx.metrics.video.available else 0.5
        return make_result(self.name, score, confidence, defects)
