"""Map a failed clip's `QAReport` onto a typed `RepairDirective` (pure, deterministic).

Attempt 1 is *targeted*: only the levers that address the diagnosed failure classes.
Attempt 2 is *escalated*: every stabilising lever (fresh opening frame, static camera,
character + key-prop references only, condensed identity text). Story content (sequence,
dialogue, clip prompt) is never rewritten; retry targets are positive (`retry_rewrite`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from ..config import QACfg
from ..omni.spec import RepairToken
from ..qa.retry_rewrite import ReasonRewriter, RewriteContext, rewrite_retry_feedback
from ..schema import QAReport
from .models import ESCALATED_DESC_LEVEL, FailureClass, RepairDirective

_FLAG_ALIASES: Final[dict[str, str]] = {
    "character_design_drift": "character_morphing",
    "action_teleportation": "teleportation",
    "corrupted_first_frame": "start_frame_bleed",
}
_FLAGS_BY_CLASS: Final[dict[FailureClass, frozenset[str]]] = {
    FailureClass.IDENTITY_DRIFT: frozenset(
        [
            "character_design_drift",
            "character_morphing",
            "duplicate_character",
            "missing_character",
            "wardrobe_mismatch",
            "face_mismatch",
        ]
    ),
    FailureClass.OBJECT_PERMANENCE: frozenset(
        [
            "object_materialized",
            "object_vanished",
            "duplicate_prop",
            "prop_part_missing",
            "prop_morphing",
            "self_moving_object",
            "floating_object",
            "prop_inverted",
            "object_state_reversal",
            "prop_mismatch",
        ]
    ),
    FailureClass.ACTION_OVERLOAD: frozenset(
        ["teleportation", "action_teleportation", "temporal_inconsistency"]
    ),
    FailureClass.SPATIAL_AXIS: frozenset({"spatial_axis_flip"}),
    FailureClass.START_FRAME: frozenset(
        {"start_frame_bleed", "frozen_frame", "corrupted_first_frame"}
    ),
    FailureClass.STYLE: frozenset({"style_drift"}),
}
_CLASS_BY_FLAG: Final[dict[str, FailureClass]] = {
    flag: cls for cls, flags in _FLAGS_BY_CLASS.items() for flag in flags
}


@dataclass(frozen=True)
class _Lever:
    """Directive fields switched on by one failure class."""

    switches: dict[str, bool] = field(default_factory=dict)
    tokens: tuple[RepairToken, ...] = ()


_LEVERS: Final[dict[FailureClass, _Lever]] = {
    FailureClass.IDENTITY_DRIFT: _Lever(
        {"character_refs_first": True}, ("character_design_matches_refs",)
    ),
    FailureClass.OBJECT_PERMANENCE: _Lever({}, ("objects_persist_whole_take",)),
    FailureClass.ACTION_OVERLOAD: _Lever({}, ("one_action_at_a_time",)),
    FailureClass.SPATIAL_AXIS: _Lever(
        {"lock_screen_positions": True, "lock_camera_static": True},
        ("screen_positions_locked", "camera_locked_static"),
    ),
    FailureClass.START_FRAME: _Lever(
        {"drop_first_frame": True}, ("motion_from_first_frame",)
    ),
    FailureClass.STYLE: _Lever({}, ("single_consistent_art_style",)),
}
_ESCALATED_TOKENS: Final[tuple[RepairToken, ...]] = (
    "character_design_matches_refs",
    "camera_locked_static",
    "motion_from_first_frame",
)
_MAX_REASONS: Final[int] = 6
_MAX_REASON_CHARS: Final[int] = 140


def _base_flag(flag: str) -> str:
    return flag.split(":", 1)[0].strip().lower()


def _flag_class(flag: str) -> FailureClass | None:
    base = _base_flag(flag)
    hit = _CLASS_BY_FLAG.get(base)
    if hit is not None:
        return hit
    return next((c for f, c in _CLASS_BY_FLAG.items() if base.startswith(f)), None)


def _score_classes(report: QAReport, qa: QACfg) -> set[FailureClass]:
    out: set[FailureClass] = set()
    faces_low = any(v < qa.face_cosine_min for v in report.face_similarity.values())
    if faces_low or report.wardrobe_match < qa.wardrobe_vlm_min:
        out.add(FailureClass.IDENTITY_DRIFT)
    if report.object_permanence < qa.permanence_vlm_min:
        out.add(FailureClass.OBJECT_PERMANENCE)
    low_action = report.action_achieved < qa.action_vlm_min
    if low_action or report.physics_plausibility < qa.physics_vlm_min:
        out.add(FailureClass.ACTION_OVERLOAD)
    return out


def classify_failures(report: QAReport, qa: QACfg) -> list[FailureClass]:
    """Failure classes from artifact flags plus below-threshold scores (stable order)."""
    found = {c for c in map(_flag_class, report.artifact_flags) if c is not None}
    found |= _score_classes(report, qa)
    return [c for c in FailureClass if c in found]


def _alias_flag(flag: str) -> str:
    base, sep, rest = flag.partition(":")
    return f"{_FLAG_ALIASES.get(base.strip().lower(), base)}{sep}{rest}"


def _targets(
    report: QAReport, ctx: RewriteContext, llm: ReasonRewriter | None
) -> list[str]:
    aliased = report.model_copy(
        update={"artifact_flags": [_alias_flag(f) for f in report.artifact_flags]}
    )
    return rewrite_retry_feedback(aliased, ctx, llm)


def _targeted(
    classes: list[FailureClass], ctx: RewriteContext, must: list[str]
) -> RepairDirective:
    fields: dict[str, Any] = {}
    tokens: list[RepairToken] = []
    for cls in classes:
        lever = _LEVERS[cls]
        fields.update(lever.switches)
        tokens.extend(lever.tokens)
    props = [p.name for p in ctx.props]
    return RepairDirective(
        attempt=1,
        failure_classes=classes,
        allow_composites=not fields.get("character_refs_first", False),
        emphasize_objects=props if FailureClass.OBJECT_PERMANENCE in classes else [],
        must_achieve=must,
        constraint_tokens=list(dict.fromkeys(tokens)),
        **fields,
    )


def escalate(directive: RepairDirective, ctx: RewriteContext) -> RepairDirective:
    """Strongest stabilising variant of `directive` (attempt 2)."""
    tokens = list(dict.fromkeys([*directive.constraint_tokens, *_ESCALATED_TOKENS]))
    return directive.model_copy(
        update={
            "attempt": 2,
            "escalated": True,
            "drop_first_frame": True,
            "lock_camera_static": True,
            "character_refs_first": True,
            "refs_characters_and_props_only": True,
            "allow_composites": False,
            "emphasize_objects": [p.name for p in ctx.props],
            "min_desc_level": max(directive.min_desc_level, ESCALATED_DESC_LEVEL),
            "constraint_tokens": tokens,
        }
    )


def diagnose_failure(
    report: QAReport,
    ctx: RewriteContext,
    qa: QACfg,
    attempt: int,
    llm: ReasonRewriter | None = None,
) -> RepairDirective:
    """Directive for repair `attempt` (1 = targeted, >=2 = escalated) from a failed QA."""
    directive = _targeted(
        classify_failures(report, qa), ctx, _targets(report, ctx, llm)
    )
    return escalate(directive, ctx) if attempt >= 2 else directive


def _humanize_flag(flag: str) -> str:
    base, _, who = flag.partition(":")
    text = base.strip().replace("_", " ")
    return f"{text} ({who.strip()})" if who.strip() else text


def manual_edit_reasons(report: QAReport | None) -> list[str]:
    """Concise, deduplicated reasons shown to the user when a shot needs manual edits."""
    if report is None:
        return ["clip could not be rendered or reviewed"]
    flags = [_humanize_flag(f) for f in report.artifact_flags]
    reasons = [
        r for r in report.failure_reasons if not r.startswith("Severe artifact flag")
    ]
    merged = [t[:_MAX_REASON_CHARS] for t in [*flags, *reasons] if t.strip()]
    return list(dict.fromkeys(merged))[:_MAX_REASONS] or ["failed clip QA"]
