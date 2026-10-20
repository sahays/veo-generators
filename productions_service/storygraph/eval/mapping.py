"""Map an `EvalReport` + gate decision back into the `QAReport` used by UI/repair/retry."""

from __future__ import annotations

from ..qa.critic.checks import norm01
from ..qa.critic.gate import GateDecision
from ..schema import DimensionScore, QAReport
from .contracts import EvalReport
from .rubric import EvalRubric


def _subs(report: EvalReport, dim: str, prefix: str) -> dict[str, float]:
    res = report.results.get(dim)
    if res is None:
        return {}
    return {
        k[len(prefix) :]: v for k, v in res.sub_scores.items() if k.startswith(prefix)
    }


def _score(report: EvalReport, dim: str, default: float = 1.0) -> float:
    res = report.results.get(dim)
    return res.score if res is not None else default


def _sub(report: EvalReport, dim: str, key: str, default: float) -> float:
    res = report.results.get(dim)
    return res.sub_scores.get(key, default) if res is not None else default


def to_qa_report(
    report: EvalReport,
    decision: GateDecision,
    dims: list[DimensionScore],
    rubric: EvalRubric,
    face_ids: dict[str, str],
) -> QAReport:
    """Populate legacy QAReport fields from dimension results (plus `dimension_scores`)."""
    identity = _subs(report, "character_consistency", "identity:")
    steps = _subs(report, "action_adherence", "step:")
    continuity = _sub(report, "scene_consistency", "continuity_prev_shot", 1.0)
    return QAReport(
        face_similarity={face_ids.get(n.lower(), n): s for n, s in identity.items()},
        identity_scores=identity,
        wardrobe_match=norm01(rubric.wardrobe_match),
        setting_match=norm01(rubric.setting_match),
        physics_plausibility=norm01(rubric.physics_plausibility),
        action_achieved=_score(report, "action_adherence"),
        object_permanence=_score(report, "object_permanence"),
        camera_match=_score(report, "camera_adherence"),
        continuity_prev_shot=continuity,
        dialogue_wer=_sub(report, "script_adherence", "dialogue_wer", 0.0),
        artifact_flags=decision.artifact_flags,
        passed=decision.passed,
        failure_reasons=decision.failure_reasons,
        suggested_fix=decision.suggested_fix,
        defects=report.defects(),
        steps_done={n: v >= 1.0 for n, v in steps.items()},
        hard_cut_times_s=report.cut_times_s,
        frames_sampled=report.frames_sampled,
        rubric_version=f"{report.version}/{report.rubric_version}",
        dimension_scores=dims,
        eval_overall=report.overall,
    )
