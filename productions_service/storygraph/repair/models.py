"""Typed contracts for automatic shot repair: failure classes, directives and reports."""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..omni.spec import RepairToken

MAX_REPAIR_ATTEMPTS: Final[int] = 2
ESCALATED_DESC_LEVEL: Final[int] = 2  # DESC_LEVELS index: condensed identity text


class FailureClass(StrEnum):
    """Root-cause buckets the critic's QA verdict is mapped onto."""

    IDENTITY_DRIFT = "identity_drift"
    OBJECT_PERMANENCE = "object_permanence"
    ACTION_OVERLOAD = "action_overload"
    SPATIAL_AXIS = "spatial_axis"
    START_FRAME = "start_frame"
    STYLE = "style"


class RepairDirective(BaseModel):
    """Render-side levers for one repair attempt. Never changes story content."""

    model_config = ConfigDict(frozen=True)

    attempt: int = 1
    escalated: bool = False
    failure_classes: list[FailureClass] = Field(default_factory=list)
    drop_first_frame: bool = False
    character_refs_first: bool = False
    refs_characters_and_props_only: bool = False
    allow_composites: bool = True
    lock_camera_static: bool = False
    lock_screen_positions: bool = False
    emphasize_objects: list[str] = Field(default_factory=list)
    min_desc_level: int = 0
    must_achieve: list[str] = Field(default_factory=list)
    constraint_tokens: list[RepairToken] = Field(default_factory=list)


ShotOutcomeKind = Literal["approved", "flagged", "skipped"]


class ShotRepairOutcome(BaseModel):
    """What happened to one shot during a repair/regenerate pass."""

    shot_id: str
    outcome: ShotOutcomeKind
    renders: int = 0
    repair_attempts: int = 0
    reasons: list[str] = Field(default_factory=list)
    continuity_follower_of: str | None = None


class RepairReport(BaseModel):
    """Per-shot outcomes of a repair pass, in processing order."""

    outcomes: list[ShotRepairOutcome] = Field(default_factory=list)

    @property
    def approved(self) -> list[str]:
        return [o.shot_id for o in self.outcomes if o.outcome == "approved"]

    @property
    def flagged(self) -> list[str]:
        return [o.shot_id for o in self.outcomes if o.outcome == "flagged"]

    @property
    def total_renders(self) -> int:
        return sum(o.renders for o in self.outcomes)

    def to_payload(self) -> dict[str, object]:
        """JSON-ready dict including the derived approved/flagged lists."""
        return {
            "outcomes": [o.model_dump(mode="json") for o in self.outcomes],
            "approved": self.approved,
            "flagged": self.flagged,
            "total_renders": self.total_renders,
        }
