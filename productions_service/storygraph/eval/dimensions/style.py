"""Style consistency: art style vs style guide and reference sheets."""

from __future__ import annotations

from ...qa.critic.checks import defect, norm01
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput
from .base import VLM_CONFIDENCE, EvalContext, make_result, routed_flags

DRIFT_SCORE = 0.3


class StyleConsistency:
    name = "style_consistency"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        rub = ctx.rubric
        defects: list[QADefect] = []
        score = norm01(rub.style.style_match)
        if rub.style_drift:
            defects.append(defect("style_drift", "high", "style", rub.style_evidence))
            score = min(score, DRIFT_SCORE)
        elif score < 0.6:
            ev = rub.style.evidence or f"style_match {score:.2f}"
            defects.append(defect("style_mismatch", "medium", "style", ev))
        defects += routed_flags(ctx, "style_consistency")
        return make_result(self.name, score, VLM_CONFIDENCE, defects)
