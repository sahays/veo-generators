"""Scoped read tools for StoryGraph role agents."""

from __future__ import annotations

from typing import Any

from ..schema import EntityType
from ..state import state_at
from ..views import entity_design_view, outline_view, scene_view, shot_view
from .registry import ToolContext


def get_outline_view(ctx: ToolContext) -> dict[str, Any]:
    return outline_view(ctx.repo).model_dump(mode="json")


def get_entity_design_view(ctx: ToolContext, entity_id: str) -> dict[str, Any]:
    return entity_design_view(ctx.repo, entity_id).model_dump(mode="json")


def get_scene_view(ctx: ToolContext, scene_id: str) -> dict[str, Any]:
    return scene_view(ctx.repo, scene_id).model_dump(mode="json")


def get_shot_view(ctx: ToolContext, shot_id: str) -> dict[str, Any]:
    return shot_view(ctx.repo, shot_id).model_dump(mode="json")


def get_entity(ctx: ToolContext, entity_id: str) -> dict[str, Any] | None:
    ent = ctx.repo.get_entity(entity_id)
    return ent.model_dump(mode="json") if ent else None


def list_entities(
    ctx: ToolContext, entity_type: str | EntityType | None = None
) -> list[dict[str, Any]]:
    et = EntityType(entity_type) if entity_type else None
    return [e.model_dump(mode="json") for e in ctx.repo.list_entities(entity_type=et)]


def get_state_at(ctx: ToolContext, entity_id: str, story_order: int) -> dict[str, str]:
    return state_at(ctx.repo, entity_id, story_order)


def get_style_guide(ctx: ToolContext) -> dict[str, Any] | None:
    sg = ctx.repo.get_style_guide()
    return sg.model_dump(mode="json") if sg else None
