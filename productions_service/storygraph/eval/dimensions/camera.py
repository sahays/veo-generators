"""Camera adherence: size/angle/move vs spec (low weight; never a hard gate)."""

from __future__ import annotations

from ...qa.critic.checks import check_camera
from ..contracts import DimensionResult, EvalInput
from .base import VLM_CONFIDENCE, EvalContext, make_result, routed_flags


class CameraAdherence:
    name = "camera_adherence"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        defects, score = check_camera(ctx.spec, ctx.rubric)
        defects += routed_flags(ctx, "camera_adherence")
        return make_result(self.name, score, VLM_CONFIDENCE, defects)
