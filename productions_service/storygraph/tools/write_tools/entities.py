"""Permissioned Entity and Appearance write tools for StoryGraph role agents."""

from __future__ import annotations

from typing import Any

from ...audit import append_audit
from ...errors import NotFound, PermissionDenied
from ...schema import (
    Appearance,
    AttributeVal,
    Entity,
    EntityType,
    Provenance,
    Role,
    StateEffect,
    Status,
)
from ..registry import ToolContext, assert_can_write, assert_entity_type_allowed

_DESIGNER_ROLES = (
    Role.CHARACTER_DESIGNER,
    Role.LOCATION_DESIGNER,
    Role.OBJECT_DESIGNER,
    Role.DESIGNER,
)


def _coerce_attribute_dict(
    base: dict[str, AttributeVal],
    updates: dict[str, AttributeVal | dict[str, Any] | str] | None,
) -> dict[str, AttributeVal]:
    parsed = dict(base)
    for k, v in (updates or {}).items():
        if isinstance(v, AttributeVal):
            parsed[k] = v
        elif isinstance(v, dict):
            parsed[k] = AttributeVal.model_validate(v)
        else:
            parsed[k] = AttributeVal(value=str(v), provenance=Provenance.FROM_TEXT)
    return parsed


def put_entity(
    ctx: ToolContext,
    entity_id: str,
    entity_type: str | EntityType,
    canonical_name: str,
    aliases: list[str] | None = None,
    attributes: dict[str, AttributeVal | dict[str, Any] | str] | None = None,
    voice_profile_id: str | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Entity")
    et = EntityType(entity_type)
    assert_entity_type_allowed(ctx.role, et)
    prev = ctx.repo.get_entity(entity_id)
    parsed_attrs = _coerce_attribute_dict(
        dict(prev.attributes) if prev else {}, attributes
    )
    ent = Entity(
        id=entity_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        entity_type=et,
        canonical_name=canonical_name,
        aliases=aliases if aliases is not None else (prev.aliases if prev else []),
        attributes=parsed_attrs,
        voice_profile_id=voice_profile_id or (prev.voice_profile_id if prev else None),
    )
    saved = ctx.repo.put_entity(ent)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_entity",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Put {et} entity '{canonical_name}'",
    )
    return saved.model_dump(mode="json")


def _cascade_event_entity_refs(ctx: ToolContext, keep_id: str, drop_id: str) -> None:
    for ev in ctx.repo.list_events():
        changed = False
        new_parts: list[str] = []
        for pid in ev.participants:
            mapped = keep_id if pid == drop_id else pid
            changed = changed or (mapped != pid)
            if mapped not in new_parts:
                new_parts.append(mapped)
        new_effs: list[StateEffect] = []
        for eff in ev.effects:
            e_ent = keep_id if eff.entity_id == drop_id else eff.entity_id
            e_val = keep_id if eff.new_value == drop_id else eff.new_value
            if e_ent != eff.entity_id or e_val != eff.new_value:
                changed = True
                new_effs.append(
                    eff.model_copy(update={"entity_id": e_ent, "new_value": e_val})
                )
            else:
                new_effs.append(eff)
        if changed:
            ctx.repo.put_event(
                ev.model_copy(update={"participants": new_parts, "effects": new_effs})
            )


def _cascade_scene_dialogue_app_refs(
    ctx: ToolContext, keep_id: str, drop_id: str
) -> None:
    for sc in ctx.repo.list_scenes():
        if sc.location_id == drop_id:
            ctx.repo.put_scene(sc.model_copy(update={"location_id": keep_id}))
    for dl in ctx.repo.list_dialogue():
        sp = keep_id if dl.speaker_id == drop_id else dl.speaker_id
        ad = keep_id if dl.addressee_id == drop_id else dl.addressee_id
        if sp != dl.speaker_id or ad != dl.addressee_id:
            ctx.repo.put_dialogue(
                dl.model_copy(update={"speaker_id": sp, "addressee_id": ad})
            )
    for app in ctx.repo.list_appearances(entity_id=drop_id, active_only=False):
        ctx.repo.store.delete("appearances", app.id)


def propose_entity_merge(
    ctx: ToolContext,
    keep_id: str,
    drop_id: str,
    reason: str = "Duplicate alias",
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Entity")
    keep = ctx.repo.get_entity(keep_id)
    drop = ctx.repo.get_entity(drop_id)
    if not keep or not drop:
        raise NotFound(f"Cannot merge '{drop_id}' into '{keep_id}': entity missing")
    merged_aliases = list(
        dict.fromkeys([*keep.aliases, drop.canonical_name, *drop.aliases])
    )
    merged_attrs = {**drop.attributes, **keep.attributes}
    saved = ctx.repo.put_entity(
        keep.model_copy(update={"aliases": merged_aliases, "attributes": merged_attrs})
    )
    ctx.repo.store.delete("entities", drop_id)
    _cascade_event_entity_refs(ctx, keep_id, drop_id)
    _cascade_scene_dialogue_app_refs(ctx, keep_id, drop_id)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "propose_entity_merge",
        saved.id,
        keep.version,
        saved.version,
        f"Merged '{drop_id}' into '{keep_id}' ({reason})",
    )
    return saved.model_dump(mode="json")


def _validate_and_coerce_attr(
    role: Role,
    entity_id: str,
    key: str,
    existing_attr: AttributeVal | None,
    raw_val: str | AttributeVal | dict[str, Any],
    prov_enum: Provenance,
) -> AttributeVal:
    if (
        existing_attr
        and existing_attr.provenance == Provenance.FROM_TEXT
        and role in _DESIGNER_ROLES
    ):
        raise PermissionDenied(
            f"Role '{role}' cannot overwrite FROM_TEXT attribute '{key}' on '{entity_id}'"
        )
    if isinstance(raw_val, AttributeVal):
        attr_obj = raw_val
    elif isinstance(raw_val, dict):
        attr_obj = AttributeVal.model_validate(raw_val)
    else:
        attr_obj = AttributeVal(value=str(raw_val), provenance=prov_enum)
    if attr_obj.provenance == Provenance.FROM_TEXT and role in _DESIGNER_ROLES:
        raise PermissionDenied(
            f"Role '{role}' can only write 'inferred' or 'invented' provenance, not 'from_text'"
        )
    return attr_obj


def set_entity_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str | AttributeVal | dict[str, Any]],
    provenance: str | Provenance = Provenance.INVENTED,
) -> dict[str, Any]:
    """Set visual/physical attributes on an Entity, enforcing entity-type isolation and preserving FROM_TEXT attributes."""
    if ctx.role not in (Role.SCRIPT_SUPERVISOR, Role.PIPELINE, Role.HUMAN):
        assert_can_write(ctx.role, "Entity.attributes")
    ent = ctx.repo.get_entity(entity_id)
    if not ent:
        raise NotFound(f"Entity {entity_id} not found")
    assert_entity_type_allowed(ctx.role, ent.entity_type)

    prov_enum = Provenance(provenance)
    merged_attrs = dict(ent.attributes)
    for k, raw_val in attributes.items():
        merged_attrs[k] = _validate_and_coerce_attr(
            ctx.role, entity_id, k, merged_attrs.get(k), raw_val, prov_enum
        )
    saved = ctx.repo.put_entity(ent.model_copy(update={"attributes": merged_attrs}))
    append_audit(
        ctx.repo.store,
        ctx.role,
        "set_entity_attributes",
        saved.id,
        ent.version,
        saved.version,
        f"Set {len(attributes)} attribute(s) on {ent.entity_type} '{entity_id}'",
    )
    return saved.model_dump(mode="json")


def _require_entity_type(
    ctx: ToolContext, entity_id: str, expected: EntityType, label: str
) -> None:
    ent = ctx.repo.get_entity(entity_id)
    if not ent or ent.entity_type != expected:
        raise PermissionDenied(
            f"Entity '{entity_id}' is not a {label} (found: {ent.entity_type if ent else None})"
        )


def set_character_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str],
    provenance: str = "invented",
) -> dict[str, Any]:
    _require_entity_type(ctx, entity_id, EntityType.CHARACTER, "character")
    return set_entity_attributes(ctx, entity_id, attributes, provenance=provenance)


def set_location_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str],
    provenance: str = "invented",
) -> dict[str, Any]:
    _require_entity_type(ctx, entity_id, EntityType.LOCATION, "location")
    return set_entity_attributes(ctx, entity_id, attributes, provenance=provenance)


def set_object_attributes(
    ctx: ToolContext,
    entity_id: str,
    attributes: dict[str, str],
    provenance: str = "invented",
) -> dict[str, Any]:
    _require_entity_type(ctx, entity_id, EntityType.OBJECT, "object")
    return set_entity_attributes(ctx, entity_id, attributes, provenance=provenance)


def add_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    wardrobe: str | None = None,
    condition_tags: list[str] | None = None,
    status: Status = Status.PROPOSED,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Appearance")
    ent = ctx.repo.get_entity(entity_id)
    if not ent:
        raise NotFound(f"Entity '{entity_id}' not found")
    assert_entity_type_allowed(ctx.role, ent.entity_type)

    app = Appearance(
        id=f"app_{entity_id}_{state_label}",
        created_by=ctx.role,
        status=status,
        entity_id=entity_id,
        state_label=state_label,
        visual_description=visual_description,
        wardrobe=wardrobe,
        condition_tags=condition_tags or [],
    )
    saved = ctx.repo.add_appearance(app)
    prev_ver = (saved.version - 1) if saved.version > 1 else None
    append_audit(
        ctx.repo.store,
        ctx.role,
        "add_appearance",
        saved.id,
        prev_ver,
        saved.version,
        f"Added appearance '{saved.id}' for {ent.entity_type} '{entity_id}'",
    )
    return saved.model_dump(mode="json")


def add_character_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    wardrobe: str | None = None,
    condition_tags: list[str] | None = None,
) -> dict[str, Any]:
    _require_entity_type(ctx, entity_id, EntityType.CHARACTER, "character")
    return add_appearance(
        ctx, entity_id, state_label, visual_description, wardrobe, condition_tags
    )


def add_location_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    condition_tags: list[str] | None = None,
) -> dict[str, Any]:
    _require_entity_type(ctx, entity_id, EntityType.LOCATION, "location")
    return add_appearance(
        ctx, entity_id, state_label, visual_description, None, condition_tags
    )


def add_object_appearance(
    ctx: ToolContext,
    entity_id: str,
    state_label: str,
    visual_description: str,
    condition_tags: list[str] | None = None,
) -> dict[str, Any]:
    _require_entity_type(ctx, entity_id, EntityType.OBJECT, "object")
    return add_appearance(
        ctx, entity_id, state_label, visual_description, None, condition_tags
    )
