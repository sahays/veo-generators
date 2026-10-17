"""Role permission matrix (`ROLE_SCOPE`), entity-type isolation, and `ToolContext`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..errors import PermissionDenied
from ..repo import Repo
from ..schema import EntityType, Role

ROLE_SCOPE: dict[Role, set[str]] = {
    Role.STORY_ARCHITECT: {"StyleGuide", "Scene", "Event", "ChangeRequest"},
    Role.SCRIPT_SUPERVISOR: {"Entity", "Event", "Scene", "ChangeRequest"},
    Role.SCREENWRITER: {"Scene", "DialogueLine", "ChangeRequest"},
    Role.CHARACTER_DESIGNER: {
        "Entity.attributes",
        "Appearance",
        "Asset",
        "ChangeRequest",
    },
    Role.LOCATION_DESIGNER: {
        "Entity.attributes",
        "Appearance",
        "Asset",
        "ChangeRequest",
    },
    Role.OBJECT_DESIGNER: {
        "Entity.attributes",
        "Appearance",
        "Asset",
        "ChangeRequest",
    },
    Role.DESIGNER: {"Entity.attributes", "Appearance", "Asset", "ChangeRequest"},
    Role.DIRECTOR: {"Shot", "ChangeRequest"},
    Role.MUSIC_DIRECTOR: {
        "MusicCue",
        "Shot.music_cue_id",
        "Shot.sfx",
        "ChangeRequest",
    },
    Role.CRITIC: {
        "GenerationRun.qa_scores",
        "GenerationRun.status",
        "Asset.qa_notes",
        "ChangeRequest",
    },
    Role.PIPELINE: {"*"},
    Role.HUMAN: {"*"},
}

ROLE_ENTITY_TYPE_SCOPE: dict[Role, set[EntityType]] = {
    Role.CHARACTER_DESIGNER: {EntityType.CHARACTER},
    Role.LOCATION_DESIGNER: {EntityType.LOCATION},
    Role.OBJECT_DESIGNER: {EntityType.OBJECT},
    Role.DESIGNER: {
        EntityType.CHARACTER,
        EntityType.LOCATION,
        EntityType.OBJECT,
    },
    Role.SCRIPT_SUPERVISOR: {
        EntityType.CHARACTER,
        EntityType.LOCATION,
        EntityType.OBJECT,
    },
    Role.PIPELINE: {
        EntityType.CHARACTER,
        EntityType.LOCATION,
        EntityType.OBJECT,
    },
    Role.HUMAN: {
        EntityType.CHARACTER,
        EntityType.LOCATION,
        EntityType.OBJECT,
    },
}

ROLE_ASSET_KIND_SCOPE: dict[Role, set[str]] = {
    Role.CHARACTER_DESIGNER: {"character_sheet"},
    Role.LOCATION_DESIGNER: {"location_plate"},
    Role.OBJECT_DESIGNER: {"prop_sheet"},
    Role.DESIGNER: {
        "character_sheet",
        "location_plate",
        "prop_sheet",
        "composite_sheet",
        "first_frame",
        "audio",
    },
    Role.PIPELINE: {
        "character_sheet",
        "location_plate",
        "prop_sheet",
        "composite_sheet",
        "first_frame",
        "audio",
    },
    Role.HUMAN: {
        "character_sheet",
        "location_plate",
        "prop_sheet",
        "composite_sheet",
        "first_frame",
        "audio",
    },
}


@dataclass
class ToolContext:
    repo: Repo
    role: Role
    cfg: Config
    image_gen: Any = None


def assert_can_write(role: Role, target_scope: str) -> None:
    allowed = ROLE_SCOPE.get(role, set())
    if "*" in allowed or target_scope in allowed:
        return
    raise PermissionDenied(
        f"Role '{role}' is not permitted to write '{target_scope}' (allowed: {sorted(allowed)})"
    )


def assert_entity_type_allowed(role: Role, entity_type: EntityType) -> None:
    if role in ROLE_ENTITY_TYPE_SCOPE:
        allowed_types = ROLE_ENTITY_TYPE_SCOPE[role]
        if entity_type not in allowed_types:
            raise PermissionDenied(
                f"Role '{role}' cannot modify entity of type '{entity_type}' "
                f"(allowed entity types: {[str(t) for t in sorted(allowed_types)]})"
            )


def assert_asset_kind_allowed(role: Role, kind: str) -> None:
    if role in ROLE_ASSET_KIND_SCOPE:
        allowed_kinds = ROLE_ASSET_KIND_SCOPE[role]
        if kind not in allowed_kinds:
            raise PermissionDenied(
                f"Role '{role}' cannot create asset of kind '{kind}' "
                f"(allowed asset kinds: {sorted(allowed_kinds)})"
            )


def _build_base_read_tools(
    ctx: ToolContext, rt: Any, wt: Any
) -> list[Callable[..., Any]]:
    def tool_get_outline_view() -> dict[str, Any]:
        """Return the story outline view (style_guide, entities, scenes, events)."""
        return rt.get_outline_view(ctx)

    def tool_get_scene_view(scene_id: str) -> dict[str, Any]:
        """Return full context for a single scene."""
        return rt.get_scene_view(ctx, scene_id)

    def tool_get_shot_view(shot_id: str) -> dict[str, Any]:
        """Return full context for a single shot."""
        return rt.get_shot_view(ctx, shot_id)

    def tool_get_entity(entity_id: str) -> dict[str, Any] | None:
        """Return a single entity by ID."""
        return rt.get_entity(ctx, entity_id)

    def tool_list_entities(entity_type: str = "") -> list[dict[str, Any]]:
        """List all entities in the graph, optionally filtered by entity_type ('character', 'location', 'object')."""
        return rt.list_entities(ctx, entity_type=entity_type or None)

    def tool_get_state_at(entity_id: str, story_order: int) -> dict[str, str]:
        """Return active state attributes for entity_id at story_order."""
        return rt.get_state_at(ctx, entity_id, story_order)

    def tool_get_style_guide() -> dict[str, Any] | None:
        """Return the project StyleGuide."""
        return rt.get_style_guide(ctx)

    def tool_create_change_request(
        to_role: str, target_node_id: str, reason: str
    ) -> dict[str, Any]:
        """File a cross-role ChangeRequest when an out-of-scope node needs modification."""
        return wt.create_change_request(ctx, to_role, target_node_id, reason, {})

    return [
        tool_get_outline_view,
        tool_get_scene_view,
        tool_get_shot_view,
        tool_get_entity,
        tool_list_entities,
        tool_get_state_at,
        tool_get_style_guide,
        tool_create_change_request,
    ]


def _build_architect_tools(ctx: ToolContext, wt: Any) -> list[Callable[..., Any]]:
    def tool_put_style_guide(
        visual_medium: str,
        palette: list[str],
        lens_language: str,
        lighting_rules: str,
        aspect_ratio: str = "16:9",
        avoid: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create or update the global StyleGuide."""
        return wt.put_style_guide(
            ctx,
            visual_medium=visual_medium,
            palette=palette,
            lens_language=lens_language,
            lighting_rules=lighting_rules,
            aspect_ratio=aspect_ratio,
            avoid=avoid or [],
        )

    def tool_put_scene(
        scene_id: str,
        index: int,
        heading: str,
        location_id: str,
        time_of_day: str,
        weather: str = "clear",
        summary: str = "",
        mood: str = "",
    ) -> dict[str, Any]:
        """Create or update a Scene node."""
        return wt.put_scene(
            ctx,
            scene_id=scene_id,
            index=index,
            heading=heading,
            location_id=location_id,
            time_of_day=time_of_day,
            weather=weather,
            summary=summary,
            mood=mood,
        )

    def tool_put_event(
        event_id: str,
        story_order: int,
        scene_id: str,
        summary: str,
        participants: list[str],
    ) -> dict[str, Any]:
        """Create or update a narrative Event node."""
        return wt.put_event(
            ctx,
            event_id=event_id,
            story_order=story_order,
            scene_id=scene_id,
            summary=summary,
            participants=participants,
            effects=[],
        )

    return [tool_put_style_guide, tool_put_scene, tool_put_event]


def _build_supervisor_tools(ctx: ToolContext, wt: Any) -> list[Callable[..., Any]]:
    def tool_put_entity(
        entity_id: str,
        entity_type: str,
        canonical_name: str,
        aliases: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create or update a canonical Entity ('character', 'location', 'object')."""
        return wt.put_entity(
            ctx,
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            aliases=aliases or [],
        )

    def tool_propose_entity_merge(
        keep_id: str, drop_id: str, reason: str
    ) -> dict[str, Any]:
        """Merge duplicate entity `drop_id` into `keep_id`."""
        return wt.propose_entity_merge(ctx, keep_id, drop_id, reason)

    return [tool_put_entity, tool_propose_entity_merge]


def _build_screenwriter_tools(ctx: ToolContext, wt: Any) -> list[Callable[..., Any]]:
    def tool_update_scene_script(
        scene_id: str, summary: str, mood: str
    ) -> dict[str, Any]:
        """Update a scene's dramatic summary and mood."""
        return wt.update_scene_script(
            ctx, scene_id=scene_id, summary=summary, mood=mood
        )

    def tool_put_dialogue(
        line_id: str,
        scene_id: str,
        order_in_scene: int,
        speaker_id: str,
        text: str,
        delivery: str = "natural",
        addressee_id: str | None = None,
        language: str = "en",
    ) -> dict[str, Any]:
        """Create or update a DialogueLine in a scene."""
        return wt.put_dialogue(
            ctx,
            line_id=line_id,
            scene_id=scene_id,
            order_in_scene=order_in_scene,
            speaker_id=speaker_id,
            text=text,
            delivery=delivery,
            addressee_id=addressee_id,
            language=language,
        )

    return [tool_update_scene_script, tool_put_dialogue]


def _build_designer_tools(ctx: ToolContext, wt: Any) -> list[Callable[..., Any]]:
    def tool_set_entity_attributes(
        entity_id: str, attributes: dict[str, str], provenance: str = "invented"
    ) -> dict[str, Any]:
        """Set physical/visual attributes on an entity within the designer's entity-type scope."""
        return wt.set_entity_attributes(
            ctx, entity_id=entity_id, attributes=attributes, provenance=provenance
        )

    def tool_add_appearance(
        entity_id: str,
        state_label: str,
        visual_description: str,
        wardrobe: str | None = None,
        condition_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new versioned Appearance node for an entity."""
        return wt.add_appearance(
            ctx,
            entity_id=entity_id,
            state_label=state_label,
            visual_description=visual_description,
            wardrobe=wardrobe,
            condition_tags=condition_tags or [],
        )

    return [tool_set_entity_attributes, tool_add_appearance]


def _build_director_and_audio_tools(
    ctx: ToolContext, wt: Any
) -> list[Callable[..., Any]]:
    if ctx.role == Role.DIRECTOR:

        def tool_put_shot(
            shot_id: str,
            scene_id: str,
            index_in_scene: int,
            story_order: int,
            duration_s: float,
            location_id: str,
            shot_size: str = "MS",
            angle: str = "eye",
            movement: str = "static",
            lens_mm: int = 35,
            continue_from_last_frame: bool = False,
        ) -> dict[str, Any]:
            """Create or update a Shot node in a scene."""
            cam = {
                "shot_size": shot_size,
                "angle": angle,
                "movement": movement,
                "lens_mm": lens_mm,
            }
            return wt.put_shot(
                ctx,
                shot_id=shot_id,
                scene_id=scene_id,
                index_in_scene=index_in_scene,
                story_order=story_order,
                duration_s=duration_s,
                location_id=location_id,
                camera=cam,
                continue_from_last_frame=continue_from_last_frame,
            )

        return [tool_put_shot]

    if ctx.role == Role.MUSIC_DIRECTOR:

        def tool_put_music_cue(
            cue_id: str,
            scene_id: str,
            mood: str,
            instrumentation: str,
            tempo_bpm: int,
            motif_tags: list[str] | None = None,
        ) -> dict[str, Any]:
            """Create or update a MusicCue for a scene."""
            return wt.put_music_cue(
                ctx,
                cue_id=cue_id,
                scene_id=scene_id,
                mood=mood,
                instrumentation=instrumentation,
                tempo_bpm=tempo_bpm,
                motif_tags=motif_tags or [],
            )

        def tool_set_shot_audio(
            shot_id: str, music_cue_id: str | None, sfx: list[str]
        ) -> dict[str, Any]:
            """Assign music_cue_id and SFX list to a Shot."""
            return wt.set_shot_audio(
                ctx, shot_id=shot_id, music_cue_id=music_cue_id, sfx=sfx
            )

        return [tool_put_music_cue, tool_set_shot_audio]

    if ctx.role == Role.CRITIC:

        def tool_record_asset_critique(
            asset_id: str, approved: bool, qa_notes: str
        ) -> dict[str, Any]:
            """Record VLM critique notes and approval status on a reference Asset."""
            return wt.record_asset_critique(
                ctx, asset_id=asset_id, approved=approved, qa_notes=qa_notes
            )

        return [tool_record_asset_critique]
    return []


def tools_for_role(ctx: ToolContext) -> list[Callable[..., Any]]:
    """Return ADK-compatible bound function tools permitted for `ctx.role`."""
    from . import read_tools as rt
    from . import write_tools as wt

    base_reads = _build_base_read_tools(ctx, rt, wt)
    role = ctx.role
    if role == Role.STORY_ARCHITECT:
        return [*base_reads, *_build_architect_tools(ctx, wt)]
    if role == Role.SCRIPT_SUPERVISOR:
        return [*base_reads, *_build_supervisor_tools(ctx, wt)]
    if role == Role.SCREENWRITER:
        return [*base_reads, *_build_screenwriter_tools(ctx, wt)]
    if role in (
        Role.CHARACTER_DESIGNER,
        Role.LOCATION_DESIGNER,
        Role.OBJECT_DESIGNER,
        Role.DESIGNER,
    ):
        return [*base_reads, *_build_designer_tools(ctx, wt)]
    return [*base_reads, *_build_director_and_audio_tools(ctx, wt)]
