"""Shared enums and the `NodeBase` root model for every graph node."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    STORY_ARCHITECT = "story_architect"
    SCRIPT_SUPERVISOR = "script_supervisor"
    SCREENWRITER = "screenwriter"
    CHARACTER_DESIGNER = "character_designer"
    LOCATION_DESIGNER = "location_designer"
    OBJECT_DESIGNER = "object_designer"
    DESIGNER = "designer"
    DIRECTOR = "director"
    MUSIC_DIRECTOR = "music_director"
    CRITIC = "critic"
    PIPELINE = "pipeline"
    HUMAN = "human"


class EntityType(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    OBJECT = "object"


class Provenance(StrEnum):
    FROM_TEXT = "from_text"
    INFERRED = "inferred"
    INVENTED = "invented"


class Status(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    RENDERED = "rendered"


class NodeBase(BaseModel):
    id: str
    node_type: str
    version: int = 1
    status: Status = Status.DRAFT
    created_by: Role
    created_at: datetime = Field(default_factory=_utc_now)
