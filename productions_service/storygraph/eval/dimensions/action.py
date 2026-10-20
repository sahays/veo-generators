"""Action adherence: every spec step done, in order, with timestamped evidence."""

from __future__ import annotations

from ...qa.critic.checks import check_steps
from ..contracts import DimensionResult, EvalInput
from .base import EvalContext, make_result

ACTION_CONFIDENCE = 0.75


class ActionAdherence:
    name = "action_adherence"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        defects, done = check_steps(ctx.spec, ctx.rubric, ctx.thr)
        score = sum(done.values()) / len(done) if done else 1.0
        subs = {f"step:{n}": float(ok) for n, ok in done.items()}
        return make_result(self.name, score, ACTION_CONFIDENCE, defects, subs)
