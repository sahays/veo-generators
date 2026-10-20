"""Legacy QAReport grading (scripted `QAReport` VLM responders and pre-rubric callers).

A VLM/responder that returns a bare `QAReport` cannot express per-step verdicts, so it is graded
by score floors + severe-flag gating; every failure is also emitted as a typed `QADefect`.
"""

from __future__ import annotations

from ...config import Config
from ...schema import QADefect, QAReport
from .checks import defect, is_severe_flag, norm01

_CONTINUITY_MIN = 0.60


def extract_severe_flags(flags: list[str]) -> set[str]:
    """Return all artifact flags denoting blocking defects."""
    return {f for f in flags if is_severe_flag(f)}


def normalize_qa_report(
    raw_report: QAReport, cfg: Config, is_mock: bool
) -> tuple[QAReport, set[str]]:
    """Normalize raw VLM scores into `[0.0, 1.0]` and identify severe artifact flags."""
    _ = cfg
    normalized = raw_report.model_copy(
        update={
            "face_similarity": {
                k: norm01(v) for k, v in raw_report.face_similarity.items()
            },
            "wardrobe_match": norm01(raw_report.wardrobe_match),
            "setting_match": norm01(raw_report.setting_match),
            "action_achieved": norm01(raw_report.action_achieved),
            "continuity_prev_shot": norm01(raw_report.continuity_prev_shot),
            "physics_plausibility": norm01(raw_report.physics_plausibility),
            "object_permanence": norm01(raw_report.object_permanence),
            "dialogue_wer": norm01(raw_report.dialogue_wer) if is_mock else 0.0,
        }
    )
    return normalized, extract_severe_flags(raw_report.artifact_flags)


def _threshold_failures(
    report: QAReport, cfg: Config, require_continuity: bool
) -> list[str]:
    """Score-floor failures for a normalized legacy report."""
    qa = cfg.qa
    checks = (
        ("Wardrobe match", report.wardrobe_match, qa.wardrobe_vlm_min, False),
        ("Setting match", report.setting_match, qa.setting_vlm_min, False),
        ("Action score", report.action_achieved, qa.action_vlm_min, False),
        (
            "Physics plausibility",
            report.physics_plausibility,
            qa.physics_vlm_min,
            False,
        ),
        ("Object permanence", report.object_permanence, qa.permanence_vlm_min, False),
        ("Dialogue WER", report.dialogue_wer, qa.dialogue_wer_max, True),
    )
    reasons = [
        f"{name} ({value:.2f}) {'>' if is_max else '<'} {limit}"
        for name, value, limit, is_max in checks
        if (value > limit if is_max else value < limit)
    ]
    if require_continuity and report.continuity_prev_shot < _CONTINUITY_MIN:
        reasons.append(
            f"Continuity with previous shot ({report.continuity_prev_shot:.2f}) < {_CONTINUITY_MIN}"
        )
    return reasons


def collect_qa_failures(
    report: QAReport,
    cfg: Config,
    is_mock: bool,
    severe_flags: set[str],
    require_continuity: bool = False,
) -> list[str]:
    """Check normalized `report` metrics against `cfg.qa` floors and severe flags."""
    reasons = list(report.failure_reasons) if (is_mock or severe_flags) else []
    for flag in sorted(severe_flags):
        msg = f"Severe artifact flag: {flag}"
        if msg not in reasons:
            reasons.append(msg)
    reasons += [
        f"Face similarity for {cid} ({sim:.2f}) < {cfg.qa.face_cosine_min}"
        for cid, sim in report.face_similarity.items()
        if sim < cfg.qa.face_cosine_min
    ]
    return reasons + _threshold_failures(report, cfg, require_continuity)


def legacy_defects(reasons: list[str]) -> list[QADefect]:
    """Typed defects for legacy failure reasons (identity vs flag vs score)."""
    out: list[QADefect] = []
    for reason in reasons:
        if reason.startswith("Face similarity"):
            out.append(defect("identity_drift", "high", "", reason))
        elif reason.startswith("Severe artifact flag"):
            out.append(defect("critic_flag", "high", reason.split(": ")[-1], reason))
        else:
            out.append(defect("low_score", "high", "", reason))
    return out
