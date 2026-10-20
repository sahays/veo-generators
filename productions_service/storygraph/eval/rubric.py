"""Sectioned VLM rubric for the eval engine: `ClipRubric` plus per-dimension sections.

One VLM call per clip fills every section. New sections default to "no issue observed" so a
legacy `ClipRubric` payload still validates; hard-gated dimensions keep relying on the
required `ClipRubric` verdicts (steps, identities, objects), so an omitted section cannot
create a false pass on its own.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..qa.critic.rubric import ClipRubric

EVAL_RUBRIC_VERSION = "eval-rubric-v1"
PhysicsKind = Literal[
    "interpenetration", "floating", "self_moving", "gravity", "contact"
]


class FeatureCheck(BaseModel):
    subject: str
    feature: str = Field(
        description="Identity feature from the spec, e.g. 'round blue eyes'."
    )
    present: bool
    evidence: str = Field(description="Observed fact with timestamps.")


class TemporalVerdict(BaseModel):
    morphing_seen: bool = False
    evidence: str = ""


class SpatialVerdict(BaseModel):
    positions_match_spec: bool = True
    axis_flip: bool = False
    relative_scale_ok: bool = True
    evidence: str = ""


class SceneVerdict(BaseModel):
    lighting_matches: bool = True
    time_of_day_matches: bool = True
    evidence: str = ""


class PhysicsIssue(BaseModel):
    kind: PhysicsKind
    subject: str
    t_s: float
    evidence: str


class StyleVerdict(BaseModel):
    style_match: float = Field(default=1.0, description="0..1 vs style guide and refs.")
    evidence: str = ""


class ScriptVerdict(BaseModel):
    beats_seen: bool = Field(default=True, description="Summary beat visibly happens.")
    entrances_exits_ok: bool = True
    unscripted_characters: list[str] = Field(default_factory=list)
    unscripted_actions: list[str] = Field(default_factory=list)
    mood_match: float = Field(default=1.0, description="0..1 delivery/mood vs spec.")
    evidence: str = ""


class EvalRubric(ClipRubric):
    """`ClipRubric` verdicts + one section per VLM-backed eval dimension."""

    feature_checks: list[FeatureCheck] = Field(default_factory=list)
    temporal: TemporalVerdict = Field(default_factory=TemporalVerdict)
    spatial: SpatialVerdict = Field(default_factory=SpatialVerdict)
    scene: SceneVerdict = Field(default_factory=SceneVerdict)
    physics_issues: list[PhysicsIssue] = Field(default_factory=list)
    style: StyleVerdict = Field(default_factory=StyleVerdict)
    script: ScriptVerdict = Field(default_factory=ScriptVerdict)


def as_eval_rubric(rubric: ClipRubric) -> EvalRubric:
    """Lift a plain `ClipRubric` (legacy responders) into an `EvalRubric` with default sections."""
    if isinstance(rubric, EvalRubric):
        return rubric
    return EvalRubric.model_validate(rubric.model_dump())
