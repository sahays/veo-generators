"""Outfit / key-prop strictness (p-0irbygdv: Ava's outfit changed, chests duplicated and the
blue cabinet vanished in APPROVED clips).

Observed wardrobe changes and timestamped in-frame count violations must block even on
dimensions calibrated with `demote_high_defects`; uncertain object defects stay demotable.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from storygraph.config import Config
from storygraph.eval.calibration.policy import (
    ClipFeatures,
    defect_counts,
    features,
    passes,
)
from storygraph.eval.contracts import DimensionResult, EvalReport
from storygraph.eval.dimensions.character import _wardrobe_change_defects
from storygraph.eval.gate import decide
from storygraph.eval.rubric import WardrobeCheck, as_eval_rubric
from storygraph.qa.critic.checks import CriticThresholds, check_objects
from storygraph.qa.critic.rubric import ClipRubric, ObjectVerdict
from storygraph.qa.critic.spec import CriticSpec, SpecObject
from storygraph.schema import QADefect


def _d(kind: str, evidence: str, sev: str = "high", subject: str = "x") -> QADefect:
    return QADefect(type=kind, severity=sev, subject=subject, evidence=evidence)  # type: ignore[arg-type]


def _results(dim: str, defects: list[QADefect]) -> dict[str, DimensionResult]:
    res = {
        k: DimensionResult(dimension=k, score=0.95, confidence=0.9)
        for k in ("character_consistency", "object_permanence", "action_adherence")
    }
    res[dim] = DimensionResult(
        dimension=dim, score=0.95, confidence=0.9, defects=defects
    )
    return res


def _features(res: dict[str, DimensionResult]) -> ClipFeatures:
    return features("run", "shot", EvalReport.model_construct(results=res))


def _passes(cfg: Config, res: dict[str, DimensionResult]) -> bool:
    real = decide(res, cfg.eval, CriticThresholds.from_cfg(cfg.qa))[0].passed
    assert passes(_features(res), cfg.eval) == real, "fast policy must mirror decide"
    return real


def test_duplicate_key_prop_with_timestamp_blocks_despite_demotion(
    default_cfg: Config,
) -> None:
    assert default_cfg.eval.for_dimension("object_permanence").demote_high_defects
    dup = _d("extra_object", "seen x3; second wooden chest at t=2.50s", subject="chest")
    assert _passes(default_cfg, _results("object_permanence", [dup])) is False


def test_vanished_prop_with_timestamp_blocks(default_cfg: Config) -> None:
    gone = _d("missing_object", "blue cabinet gone at t=4.00s", subject="cabinet")
    assert _passes(default_cfg, _results("object_permanence", [gone])) is False


def test_uncertain_object_defect_is_still_demoted(default_cfg: Config) -> None:
    vague = _d("extra_object", "possibly a second chest", subject="chest")
    state = _d("object_state", "lid open at t=3.00s", subject="chest")
    res = _results("object_permanence", [vague, state])
    assert defect_counts(_features(res), default_cfg.eval) == (0, 2)
    assert _passes(default_cfg, res) is True


def test_wardrobe_change_blocks_even_if_character_dimension_demotes(
    default_cfg: Config,
) -> None:
    cfg = default_cfg.model_copy(deep=True)
    cfg.eval.dimensions["character_consistency"].demote_high_defects = True
    change = _d("wardrobe_change", "outfit changes at t=1.00s", subject="Ava")
    assert _passes(cfg, _results("character_consistency", [change])) is False


def _ctx(checks: list[WardrobeCheck]) -> Any:
    rubric = as_eval_rubric(ClipRubric.mock_response(""))
    return cast(
        Any,
        SimpleNamespace(rubric=rubric.model_copy(update={"wardrobe_checks": checks})),
    )


def test_wardrobe_check_emits_high_change_with_subject_and_timestamps() -> None:
    swap = WardrobeCheck(
        subject="Ava",
        garments_seen="t=0s red scarf, blue dress; t=3s green jacket",
        matches_reference=False,
        changed_between_frames=True,
        timestamps_s=[3.0, 4.5],
        evidence="dress replaced by green jacket at t=3.0s",
    )
    ok = swap.model_copy(
        update={
            "subject": "Ben",
            "matches_reference": True,
            "changed_between_frames": False,
        }
    )
    (d,) = _wardrobe_change_defects(_ctx([swap, ok]))
    assert (d.type, d.severity, d.subject) == ("wardrobe_change", "high", "Ava")
    assert d.evidence.startswith(
        "outfit changes between frames vs REFERENCE at t=3.00s, t=4.50s"
    )


def _verdict(**kw: Any) -> ObjectVerdict:
    base: dict[str, Any] = {
        "object": "blue cabinet",
        "in_frame_expected": True,
        "max_instances_seen": 1,
        "start_matches": True,
        "end_matches": True,
        "evidence": "cabinet disappears at t=4.00s",
        "spec_conflict": False,
    }
    return ObjectVerdict(**{**base, **kw})


def test_mid_clip_disappearance_is_a_high_missing_object() -> None:
    spec = CriticSpec(objects=[SpecObject(oid="O1", name="blue cabinet")])
    rubric = ClipRubric.mock_response("").model_copy(
        update={"objects": [_verdict(min_instances_seen=0)]}
    )
    (d,), _score = check_objects(spec, rubric)
    assert (d.type, d.severity) == ("missing_object", "high")
    assert "min x0" in d.evidence
    clean = rubric.model_copy(update={"objects": [_verdict(min_instances_seen=1)]})
    assert check_objects(spec, clean)[0] == []


# Live p-0irbygdv re-score (eval-rubric-v2): the VLM reported min x0 for props that were
# only occluded, contained or panned past. These must not block; a real vanish must.
_NOT_VANISHED = (
    "Brass key is retrieved from the box starting at t=7.25s.",
    "Visible on screen left from t=0.00s to t=6.00s before tracking pans right.",
    "Drawn from drawer at t=4.50s-5.75s, then vanishes after t=6.50s when the drawer shuts.",
    "Held in Pip's left hand at t=0.00s-3.50s, obscured in later frames.",
    "Green cloth appears inside lower drawer at t=4.50s and is lifted by Pip until t=5.50s.",
    "Key held in hand around t=0.00s-4.00s, less visible later in motion.",
)


def test_occluded_or_contained_props_are_not_count_violations() -> None:
    spec = CriticSpec(objects=[SpecObject(oid="O1", name="blue cabinet")])
    for evidence in _NOT_VANISHED:
        rubric = ClipRubric.mock_response("").model_copy(
            update={"objects": [_verdict(min_instances_seen=0, evidence=evidence)]}
        )
        (d,), _ = check_objects(spec, rubric)
        assert d.severity == "low", evidence
    real = "blue cabinet against the wall disappears at t=4.00s while the wall stays in view"
    rubric = ClipRubric.mock_response("").model_copy(
        update={"objects": [_verdict(min_instances_seen=0, evidence=real)]}
    )
    assert check_objects(spec, rubric)[0][0].severity == "high"
