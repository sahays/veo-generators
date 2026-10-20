"""Physical plausibility: contact, gravity, interpenetration, self-moving objects."""

from __future__ import annotations

from ...qa.critic.checks import defect, norm01
from ...qa.critic.severity import Severity, score_breach_severity
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput
from .base import VLM_CONFIDENCE, EvalContext, make_result, routed_flags

_ISSUE_SEVERITY: dict[str, Severity] = {
    "interpenetration": "high",
    "floating": "high",
    "self_moving": "high",
    "gravity": "medium",
    "contact": "medium",
}


class PhysicalPlausibility:
    name = "physical_plausibility"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        value, floor = norm01(ctx.rubric.physics_plausibility), ctx.thr.physics_min
        defects: list[QADefect] = []
        if value < floor:
            msg = f"physics_plausibility {value:.2f} below {floor:.2f}"
            sev = score_breach_severity(value, floor)
            defects.append(defect("low_score", sev, "physics_plausibility", msg))
        for issue in ctx.rubric.physics_issues:
            msg = f"t={issue.t_s:.2f}s {issue.evidence}"
            sev = _ISSUE_SEVERITY[issue.kind]
            defects.append(defect(f"physics_{issue.kind}", sev, issue.subject, msg))
        defects += routed_flags(ctx, "physical_plausibility")
        score = min(value, 1.0 - 0.25 * len(ctx.rubric.physics_issues))
        return make_result(self.name, score, VLM_CONFIDENCE, defects)
