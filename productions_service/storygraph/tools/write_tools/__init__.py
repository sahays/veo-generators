"""Permissioned write tools for StoryGraph role agents, enforcing ROLE_SCOPE and audit logging."""

from __future__ import annotations

from .entities import (
    add_appearance,
    add_character_appearance,
    add_location_appearance,
    add_object_appearance,
    propose_entity_merge,
    put_entity,
    set_character_attributes,
    set_entity_attributes,
    set_location_attributes,
    set_object_attributes,
)
from .scenes import (
    put_dialogue,
    put_event,
    put_scene,
    put_style_guide,
    update_scene_script,
)
from .shots_and_assets import (
    _generate_entity_asset_with_adapter,
    create_change_request,
    generate_character_asset,
    generate_location_asset,
    generate_object_asset,
    put_music_cue,
    put_shot,
    record_asset_critique,
    record_clip_qa,
    register_asset,
    set_shot_audio,
)

__all__ = [
    "_generate_entity_asset_with_adapter",
    "add_appearance",
    "add_character_appearance",
    "add_location_appearance",
    "add_object_appearance",
    "create_change_request",
    "generate_character_asset",
    "generate_location_asset",
    "generate_object_asset",
    "propose_entity_merge",
    "put_dialogue",
    "put_entity",
    "put_event",
    "put_music_cue",
    "put_scene",
    "put_shot",
    "put_style_guide",
    "record_asset_critique",
    "record_clip_qa",
    "register_asset",
    "set_character_attributes",
    "set_entity_attributes",
    "set_location_attributes",
    "set_object_attributes",
    "set_shot_audio",
    "update_scene_script",
]
