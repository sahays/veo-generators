"""Spatial consistency: screen axis (180° rule), spec screen positions, scale, seam positions."""

from __future__ import annotations

from ...qa.critic.checks import defect
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput
from .base import EvalContext, make_result, routed_flags

SPATIAL_CONFIDENCE = 0.6


class SpatialConsistency:
    name = "spatial_consistency"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        sp = ctx.rubric.spatial
        ev = sp.evidence or "spatial check"
        checks = [sp.positions_match_spec, not sp.axis_flip, sp.relative_scale_ok]
        defects: list[QADefect] = []
        if sp.axis_flip:
            defects.append(defect("screen_axis_flip", "medium", "camera", ev))
        if not sp.positions_match_spec:
            defects.append(defect("screen_position", "medium", "subjects", ev))
        if not sp.relative_scale_ok:
            defects.append(defect("relative_scale", "low", "subjects", ev))
        if ctx.signals.has_prev_frame:
            checks.append(ctx.rubric.continuity.positions_match)
        defects += routed_flags(ctx, "spatial_consistency")
        score = sum(checks) / len(checks)
        return make_result(self.name, score, SPATIAL_CONFIDENCE, defects)
