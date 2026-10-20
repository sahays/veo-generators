"""Clip-level rubric checks and the deterministic approval gate.

Gate rule (identical on every attempt): ANY high-severity defect blocks approval regardless of
averaged scores; more than `max_medium_defects` medium defects also block. Failure reasons are
rendered from defects as short observed facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ...schema import QADefect
from .checks import (
    Cause,
    CriticThresholds,
    MediaSignals,
    check_camera,
    check_cuts,
    check_identities,
    check_objects,
    check_steps,
    defect,
    is_severe_flag,
    norm01,
)
from .rubric import ClipRubric
from .spec import CriticSpec

SuggestedFix = Literal["none", "retry_seed", "recompile_prompt", "redesign_asset"]

# Defect types mapped onto artifact flags understood by retry_rewrite / render gating.
_FLAG_FOR_DEFECT: dict[str, str] = {
    "extra_object": "duplicate_prop",
    "missing_object": "object_vanished",
    "object_state": "prop_mismatch",
    "identity_drift": "character_morphing",
    "style_drift": "style_drift",
    "hard_cut": "temporal_inconsistency",
    "wrong_speaker": "wrong_speaker",
}
_FIX_FOR_CAUSE: dict[str, SuggestedFix] = {
    "spec": "recompile_prompt",
    "reference": "redesign_asset",
    "render": "retry_seed",
}


@dataclass
class CriticOutcome:
    """All rubric results for one clip (pre-gate)."""

    defects: list[QADefect] = field(default_factory=list)
    identity_scores: dict[str, float] = field(default_factory=dict)
    steps_done: dict[str, bool] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    cut_times_s: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    failure_reasons: list[str]
    suggested_fix: SuggestedFix
    artifact_flags: list[str]


def check_continuity(
    spec: CriticSpec, rubric: ClipRubric, sig: MediaSignals
) -> tuple[list[QADefect], float]:
    """Setting layout and screen positions vs the previous approved clip's last frame."""
    if not sig.has_prev_frame:
        return [], 1.0
    cont = rubric.continuity
    oks = (cont.setting_layout_matches, cont.positions_match)
    score = round(sum(oks) / len(oks), 3)
    if all(oks):
        return [], score
    cause: Cause = "render" if spec.chained_first_frame else "spec"
    msg = f"vs previous last frame: {cont.evidence}"
    return [defect("continuity_break", "high", "setting", msg, cause)], score


def check_speech(
    spec: CriticSpec, rubric: ClipRubric, sig: MediaSignals, thr: CriticThresholds
) -> list[QADefect]:
    """Speakers must be audible/mouthing; subjects without lines must not lip-sync."""
    mouth = {v.subject.strip().lower(): v.mouth_moving for v in rubric.speech}
    speakers = {s.lower() for s in spec.speakers}
    defects: list[QADefect] = []
    for subj in spec.subjects:
        moving = mouth.get(subj.name.lower(), False)
        if subj.name.lower() not in speakers and moving:
            sev: Literal["high", "medium"] = "high" if subj.can_speak else "medium"
            msg = "mouth moves although the spec gives no line"
            defects.append(defect("wrong_speaker", sev, subj.name, msg))
        elif subj.name.lower() in speakers and subj.has_mouth and not moving:
            msg = "spec line assigned but no mouth movement seen"
            defects.append(defect("speech_missing", "medium", subj.name, msg))
    silent = sig.voiced_ratio is not None and sig.voiced_ratio < thr.min_voiced_ratio
    if spec.speakers and silent:
        msg = f"audio voiced ratio {sig.voiced_ratio:.2f}; spec has spoken lines"
        defects.append(defect("speech_missing", "high", spec.speakers[0], msg))
    return defects


def check_flags(rubric: ClipRubric, sig: MediaSignals) -> list[QADefect]:
    """The critic's own drift flags and CV anomaly flags (severe ones block)."""
    flags = list(dict.fromkeys([*rubric.drift_flags, *sig.cv_flags]))
    return [
        defect(
            "critic_flag",
            "high" if is_severe_flag(f) else "low",
            f,
            f"flagged '{f}' during frame review",
        )
        for f in flags
    ]


def check_scores(rubric: ClipRubric, thr: CriticThresholds) -> list[QADefect]:
    """Style drift plus setting/wardrobe/physics score floors."""
    defects: list[QADefect] = []
    if rubric.style_drift:
        defects.append(defect("style_drift", "high", "style", rubric.style_evidence))
    floors = (
        ("setting_match", norm01(rubric.setting_match), thr.setting_min),
        ("wardrobe_match", norm01(rubric.wardrobe_match), thr.wardrobe_min),
        ("physics_plausibility", norm01(rubric.physics_plausibility), thr.physics_min),
    )
    for name, value, floor in floors:
        if value < floor:
            msg = f"{name} {value:.2f} below {floor:.2f}"
            defects.append(defect("low_score", "high", name, msg))
    return defects


def evaluate_rubric(
    spec: CriticSpec, rubric: ClipRubric, sig: MediaSignals, thr: CriticThresholds
) -> CriticOutcome:
    """Run every rubric check against the spec and media signals."""
    step_d, steps_done = check_steps(spec, rubric, thr)
    id_d, id_scores = check_identities(spec, rubric, thr)
    obj_d, permanence = check_objects(spec, rubric)
    cam_d, camera = check_camera(spec, rubric)
    cut_d, cuts = check_cuts(spec, rubric, sig, thr)
    cont_d, continuity = check_continuity(spec, rubric, sig)
    others = [
        *check_speech(spec, rubric, sig, thr),
        *check_flags(rubric, sig),
        *check_scores(rubric, thr),
    ]
    total_steps = len(steps_done)
    action = sum(steps_done.values()) / total_steps if total_steps else 1.0
    scores = {
        "action_achieved": round(action, 3),
        "object_permanence": permanence,
        "camera_match": camera,
        "continuity_prev_shot": continuity,
    }
    return CriticOutcome(
        defects=[*step_d, *id_d, *obj_d, *cam_d, *cut_d, *cont_d, *others],
        identity_scores=id_scores,
        steps_done=steps_done,
        scores=scores,
        cut_times_s=cuts,
    )


def _reason(d: QADefect) -> str:
    """Render one defect as a concise, evidence-based observed fact."""
    subject = f" [{d.subject}]" if d.subject else ""
    return f"{d.type}{subject}: {d.evidence}"


def gate(defects: list[QADefect], thr: CriticThresholds) -> GateDecision:
    """Deterministic approval: block on any high defect or too many medium defects."""
    high = [d for d in defects if d.severity == "high"]
    medium = [d for d in defects if d.severity == "medium"]
    blocking = high + (medium if len(medium) > thr.max_medium_defects else [])
    flags = [_FLAG_FOR_DEFECT[d.type] for d in defects if d.type in _FLAG_FOR_DEFECT]
    flags += [d.subject for d in defects if d.type == "critic_flag"]
    if not blocking:
        return GateDecision(True, [], "none", list(dict.fromkeys(flags)))
    causes = {d.likely_cause for d in blocking}
    fix_cause = next(
        c for c in ("spec", "reference", "render") if c in causes or c == "render"
    )
    reasons = list(dict.fromkeys(_reason(d) for d in blocking))
    return GateDecision(
        False, reasons, _FIX_FOR_CAUSE[fix_cause], list(dict.fromkeys(flags))
    )
