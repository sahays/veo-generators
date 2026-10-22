"""Character consistency: identity vs reference sheets (VLM checklist + embedding similarity)."""

from __future__ import annotations

from ...qa.critic.checks import check_identities, defect, norm01
from ...qa.critic.severity import WARDROBE_CHANGE, score_breach_severity
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput, Evidence
from .base import VLM_CONFIDENCE, EvalContext, concrete, make_result, routed_flags

EMBED_BLEND = 0.3
EMBED_TRUSTED = 0.7


def _feature_defects(ctx: EvalContext) -> tuple[list[QADefect], float]:
    """Spec-derived identity features the VLM did not see (ratio present in [0, 1])."""
    checks = ctx.rubric.feature_checks
    missing = [c for c in checks if not c.present]
    defects = [
        defect(
            "identity_feature",
            concrete(c.evidence),
            c.subject,
            f"{c.feature}: {c.evidence}",
        )
        for c in missing
    ]
    return defects, (1.0 - len(missing) / len(checks)) if checks else 1.0


def _wardrobe_defects(ctx: EvalContext) -> list[QADefect]:
    value, floor = norm01(ctx.rubric.wardrobe_match), ctx.thr.wardrobe_min
    if value >= floor:
        return []
    msg = f"wardrobe_match {value:.2f} below {floor:.2f}"
    return [
        defect("low_score", score_breach_severity(value, floor), "wardrobe_match", msg)
    ]


def _wardrobe_change_defects(ctx: EvalContext) -> list[QADefect]:
    """HIGH `wardrobe_change` per subject whose outfit mismatches REFERENCE or changes."""
    out: list[QADefect] = []
    for c in ctx.rubric.wardrobe_checks:
        if c.matches_reference and not c.changed_between_frames:
            continue
        what = "changes between frames" if c.changed_between_frames else "differs"
        stamps = ", ".join(f"t={t:.2f}s" for t in c.timestamps_s) or "t=unknown"
        msg = f"outfit {what} vs REFERENCE at {stamps}; seen {c.garments_seen}; {c.evidence}"
        out.append(defect(WARDROBE_CHANGE, "high", c.subject, msg))
    return out


def _embedding_notes(ctx: EvalContext) -> tuple[list[Evidence], float | None]:
    sim = ctx.metrics.similarity
    notes = [
        Evidence(note=f"{sim.embedder} similarity vs {label}: {value:.2f}")
        for label, value in sim.identity.items()
    ]
    trusted = sim.confidence >= EMBED_TRUSTED and sim.identity
    return notes, (min(sim.identity.values()) if trusted else None)


class CharacterConsistency:
    name = "character_consistency"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        id_defects, scores = check_identities(ctx.spec, ctx.rubric, ctx.thr)
        feat_defects, feat_ratio = _feature_defects(ctx)
        notes, embed = _embedding_notes(ctx)
        vlm = min(scores.values()) if scores else 1.0
        score = min(vlm, 0.4 + 0.6 * feat_ratio)
        if embed is not None:
            score = (1 - EMBED_BLEND) * score + EMBED_BLEND * embed
        defects = [
            *id_defects,
            *feat_defects,
            *_wardrobe_defects(ctx),
            *_wardrobe_change_defects(ctx),
            *routed_flags(ctx, "character_consistency"),
        ]
        confidence = VLM_CONFIDENCE + (0.2 if embed is not None else 0.0)
        subs = {f"identity:{k}": v for k, v in scores.items()}
        return make_result(self.name, score, confidence, defects, subs, notes)
