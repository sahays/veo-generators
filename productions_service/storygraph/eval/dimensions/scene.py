"""Scene consistency: setting layout & lighting vs location reference and previous clip."""

from __future__ import annotations

from ...qa.critic.checks import defect, norm01
from ...qa.critic.gate import check_continuity
from ...qa.critic.severity import score_breach_severity
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput, Evidence
from .base import VLM_CONFIDENCE, EvalContext, make_result


def _setting_defects(ctx: EvalContext, value: float) -> list[QADefect]:
    floor = ctx.thr.setting_min
    if value >= floor:
        return []
    msg = f"setting_match {value:.2f} below {floor:.2f}"
    return [
        defect("low_score", score_breach_severity(value, floor), "setting_match", msg)
    ]


def _look_defects(ctx: EvalContext) -> list[QADefect]:
    sc = ctx.rubric.scene
    ev = sc.evidence or "scene look check"
    out: list[QADefect] = []
    if not sc.lighting_matches:
        out.append(defect("lighting_mismatch", "medium", "setting", ev))
    if not sc.time_of_day_matches:
        out.append(defect("time_of_day_mismatch", "medium", "setting", ev))
    return out


def _embedding_notes(ctx: EvalContext) -> list[Evidence]:
    sim = ctx.metrics.similarity
    notes: list[Evidence] = []
    if sim.setting is not None:
        notes.append(
            Evidence(note=f"{sim.embedder} setting similarity {sim.setting:.2f}")
        )
    if sim.prev_seam is not None:
        notes.append(
            Evidence(t_s=0.0, note=f"seam similarity vs previous {sim.prev_seam:.2f}")
        )
    return notes


class SceneConsistency:
    name = "scene_consistency"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        setting = norm01(ctx.rubric.setting_match)
        cont_defects, cont_score = check_continuity(ctx.spec, ctx.rubric, ctx.signals)
        sc = ctx.rubric.scene
        parts = [setting, float(sc.lighting_matches), float(sc.time_of_day_matches)]
        if ctx.signals.has_prev_frame:
            parts.append(cont_score)
        defects = [*_setting_defects(ctx, setting), *cont_defects, *_look_defects(ctx)]
        notes = _embedding_notes(ctx)
        confidence = VLM_CONFIDENCE + (0.1 if notes else 0.0)
        subs = {"setting_match": setting, "continuity_prev_shot": cont_score}
        return make_result(self.name, min(parts), confidence, defects, subs, notes)
