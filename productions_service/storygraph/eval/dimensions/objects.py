"""Object permanence: stable counts, no appear/vanish/duplicate, end state per spec.

Spec objects with `in_frame=False` (offscreen set dressing) are never expected in view; the
calibrated severity rules in `qa.critic.severity` apply (out of frame is not missing).
"""

from __future__ import annotations

from ...qa.critic.checks import check_objects
from ..contracts import DimensionResult, EvalInput
from .base import EvalContext, make_result, routed_flags

OBJECT_CONFIDENCE = 0.75


class ObjectPermanence:
    name = "object_permanence"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        defects, permanence = check_objects(ctx.spec, ctx.rubric)
        defects += routed_flags(ctx, "object_permanence")
        subs = {f"in_frame:{o.name}": float(o.in_frame) for o in ctx.spec.objects}
        return make_result(self.name, permanence, OBJECT_CONFIDENCE, defects, subs)
