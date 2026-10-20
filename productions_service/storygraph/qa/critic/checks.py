"""Deterministic rubric checks: turn VLM verdicts + media signals into typed `QADefect`s.

Each check judges ONLY items present in the compiled spec (`CriticSpec`) for this clip. A spec
item without a VLM verdict is itself a high-severity defect (an unverified clip never passes).
Thresholds come from `CriticThresholds`, which is attempt-independent by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...config import QACfg
from ...schema import QADefect
from .rubric import ClipRubric, ObjectVerdict
from .severity import Severity, camera_severity, cut_severity, object_severity
from .spec import CriticSpec, SpecObject

Cause = Literal["spec", "render", "reference"]

_SEVERE_FLAG_TOKENS: tuple[str, ...] = (
    "drift",
    "inconsisten",
    "morph",
    "duplicate",
    "missing",
    "vanish",
    "materializ",
    "hallucinat",
    "wrong_",
    "mismatch",
    "frozen_frame",
    "start_frame_bleed",
    "anatomy_glitch",
    "text_overlay",
    "extreme_blur",
    "dropout",
    "axis_flip",
    "overlap",
    "self_moving",
    "inverted",
    "deformation",
    "floating",
    "support_surface",
    "prop_part",
)


@dataclass(frozen=True)
class CriticThresholds:
    """Single rubric threshold set; deliberately has no notion of attempt number."""

    identity_min: float
    setting_min: float
    wardrobe_min: float
    physics_min: float
    cut_ignore_head_s: float = 0.25
    cut_ignore_tail_s: float = 0.10
    min_voiced_ratio: float = 0.05
    max_renderable_steps: int = 3
    max_medium_defects: int = 2  # >= 3 medium defects block

    @classmethod
    def from_cfg(cls, qa: QACfg) -> CriticThresholds:
        return cls(
            identity_min=qa.face_cosine_min,
            setting_min=qa.setting_vlm_min,
            wardrobe_min=qa.wardrobe_vlm_min,
            physics_min=qa.physics_vlm_min,
        )


@dataclass(frozen=True)
class MediaSignals:
    """Deterministic (non-VLM) measurements of the rendered clip."""

    duration_s: float = 0.0
    cut_times_s: tuple[float, ...] = ()
    voiced_ratio: float | None = None
    cv_flags: tuple[str, ...] = ()
    has_prev_frame: bool = False
    frames_sampled: int = 0


def norm01(value: float) -> float:
    """Normalize a VLM score given as 0..1, 0..10 or 0..100 into `[0, 1]`."""
    if value > 10.0:
        value = value / 100.0
    elif value > 1.0:
        value = value / 10.0
    return round(min(1.0, max(0.0, value)), 3)


def defect(
    kind: str, severity: Severity, subject: str, evidence: str, cause: Cause = "render"
) -> QADefect:
    """Construct a concise defect (evidence trimmed to keep failure reasons readable)."""
    return QADefect(
        type=kind,
        severity=severity,
        subject=subject,
        evidence=evidence.strip()[:220],
        likely_cause=cause,
    )


def is_severe_flag(flag: str) -> bool:
    """True if a free-form critic/CV flag denotes a blocking defect."""
    low = flag.lower()
    return any(token in low for token in _SEVERE_FLAG_TOKENS)


def check_steps(
    spec: CriticSpec, rubric: ClipRubric, thr: CriticThresholds
) -> tuple[list[QADefect], dict[str, bool]]:
    """Every spec step needs a 'done' verdict; overloaded specs route undone steps to spec."""
    by_n = {v.n: v for v in rubric.steps}
    overloaded = len(spec.steps) > thr.max_renderable_steps
    defects: list[QADefect] = []
    done: dict[str, bool] = {}
    for step in spec.steps:
        verdict = by_n.get(step.n)
        done[str(step.n)] = bool(verdict and verdict.done)
        if verdict is None:
            msg = f"no verdict for step {step.n}: {step.text}"
            defects.append(defect("step_unverified", "high", step.actor, msg))
        elif not verdict.done:
            cause: Cause = "spec" if verdict.spec_conflict or overloaded else "render"
            msg = f"step {step.n} '{step.text}' not observed; {verdict.evidence}"
            defects.append(defect("step_not_done", "high", step.actor, msg, cause))
    return defects, done


def check_identities(
    spec: CriticSpec, rubric: ClipRubric, thr: CriticThresholds
) -> tuple[list[QADefect], dict[str, float]]:
    """Per-subject identity vs REFERENCE; missing verdicts score 0.0 and block."""
    by_name = {v.subject.strip().lower(): v for v in rubric.identities}
    if not spec.subjects:
        return [], {v.subject: norm01(v.score) for v in rubric.identities}
    defects: list[QADefect] = []
    scores: dict[str, float] = {}
    for subj in spec.subjects:
        verdict = by_name.get(subj.name.lower())
        scores[subj.name] = norm01(verdict.score) if verdict else 0.0
        if verdict is None:
            msg = f"no identity verdict for {subj.name}"
            defects.append(defect("identity_unverified", "high", subj.name, msg))
        elif verdict.drift or scores[subj.name] < thr.identity_min:
            cause: Cause = "render" if subj.has_ref else "reference"
            msg = f"vs REFERENCE score {scores[subj.name]:.2f}; {verdict.evidence}"
            defects.append(defect("identity_drift", "high", subj.name, msg, cause))
    return defects, scores


def _object_issue(count: int, start_ok: bool, end_ok: bool) -> str | None:
    """Classify one object verdict into a defect type (None when it matches the spec)."""
    if count > 1:
        return "extra_object"
    if count < 1:
        return "missing_object"
    if not (start_ok and end_ok):
        return "object_state"
    return None


def _object_defect(obj: SpecObject, verdict: ObjectVerdict) -> QADefect | None:
    """One calibrated defect for an object verdict (framing-aware, evidence-gated)."""
    kind = _object_issue(
        verdict.max_instances_seen, verdict.start_matches, verdict.end_matches
    )
    if kind is None:
        return None
    in_frame = obj.in_frame and verdict.in_frame_expected
    sev = object_severity(kind, in_frame, verdict.evidence)
    cause: Cause = "spec" if verdict.spec_conflict else "render"
    framing = "" if in_frame else "outside framing; "
    msg = (
        f"{framing}seen x{verdict.max_instances_seen}; spec start '{obj.start}' "
        f"end '{obj.end or obj.start}'; {verdict.evidence}"
    )
    return defect(kind, sev, obj.name, msg, cause)


def check_objects(spec: CriticSpec, rubric: ClipRubric) -> tuple[list[QADefect], float]:
    """Counts (exactly one instance), start/end placement and holders vs the spec."""
    by_name = {v.object.strip().lower(): v for v in rubric.objects}
    defects: list[QADefect] = []
    for obj in spec.objects:
        verdict = by_name.get(obj.name.lower())
        if verdict is None:
            msg = f"no verdict for object {obj.name}"
            defects.append(defect("object_unverified", "high", obj.name, msg))
            continue
        found = _object_defect(obj, verdict)
        if found is not None:
            defects.append(found)
    total = len(spec.objects)
    real = sum(1 for d in defects if d.severity != "low")
    return defects, round(1.0 - real / total, 3) if total else 1.0


def check_camera(spec: CriticSpec, rubric: ClipRubric) -> tuple[list[QADefect], float]:
    """Camera vs spec: size-only deviation LOW, angle/move deviation MEDIUM, never HIGH."""
    cam = rubric.camera
    oks = (cam.size_matches, cam.angle_matches, cam.move_matches)
    score = round(sum(oks) / len(oks), 3)
    sev = camera_severity(*oks)
    if sev is None:
        return [], score
    want = f"{spec.camera.size}/{spec.camera.angle}/{spec.camera.move}"
    cause: Cause = "spec" if cam.spec_conflict else "render"
    msg = f"spec {want}; observed {cam.observed}"
    return [defect("camera_mismatch", sev, "camera", msg, cause)], score


def check_cuts(
    spec: CriticSpec, rubric: ClipRubric, sig: MediaSignals, thr: CriticThresholds
) -> tuple[list[QADefect], list[float]]:
    """Hard cuts inside a single-take clip (ffmpeg scene detection OR the VLM's own eye).

    Late cuts are trimmed before storage (`adapters.clip_trim`); any cut still present is a
    MEDIUM defect (LOW when it falls in the late, trimmable window), never HIGH.
    """
    duration = sig.duration_s or spec.duration_s
    end = (duration or 1e9) - thr.cut_ignore_tail_s
    cuts = [t for t in sig.cut_times_s if thr.cut_ignore_head_s < t < end]
    if not spec.single_take or not (cuts or rubric.hard_cut_seen):
        return [], cuts
    if not cuts:
        return [defect("hard_cut", "medium", "clip", rubric.hard_cut_evidence)], cuts
    stamps = ", ".join(f"t={t:.2f}s" for t in cuts)
    sev = cut_severity(min(cuts), duration)
    return [defect("hard_cut", sev, "clip", f"scene cut at {stamps} (ffmpeg)")], cuts
