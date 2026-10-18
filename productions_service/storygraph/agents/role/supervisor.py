"""SCRIPT_SUPERVISOR role agent runner (`script_supervisor_agent`) and fuzzy entity deduplication."""

from __future__ import annotations

from ...adapters.mock import MockLLMClient
from ...repo import Repo
from ...schema import (
    AttributeVal,
    Entity,
    EntityType,
    Event,
    Provenance,
    Role,
    Scene,
    StateEffect,
)
from ...state import rebuild_state_facts
from ...tools import write_tools as wt
from ...tools.registry import ToolContext
from ...tools.role_helpers import (
    EventDraft,
    ExtractedEntityDraft,
    ScriptSupervisorOutput,
    extract_entities_from_story,
    name_similarity,
    normalize_entity_id,
    normalize_indian_epic_names,
    slug_id,
    strip_honorifics,
)
from ..runner import RoleRunResult, run_role
from .architect import _normalize_event_effects


def _find_matching_entity(
    cand: Entity, pool: list[Entity], exact_idx: dict[str, Entity], threshold: float
) -> Entity | None:
    """Return an existing entity in `pool` matching `cand` by exact honorific-stripped name or RapidFuzz ratio."""
    cand_names = [n.strip() for n in [cand.canonical_name, *cand.aliases] if n.strip()]
    for nm in cand_names:
        hit = exact_idx.get(strip_honorifics(nm).lower())
        if hit is not None:
            return hit
    for ex in pool:
        ex_names = [n.strip() for n in [ex.canonical_name, *ex.aliases] if n.strip()]
        if any(
            name_similarity(a, b) >= threshold for a in cand_names for b in ex_names
        ):
            return ex
    return None


def _merge_within_type(
    ctx: ToolContext, entities: list[Entity], threshold: float
) -> list[str]:
    """Merge duplicate entities within a single `EntityType`."""
    dropped: list[str] = []
    kept: list[Entity] = []
    exact_idx: dict[str, Entity] = {}
    for cand in entities:
        matched = _find_matching_entity(cand, kept, exact_idx, threshold)
        if matched is not None:
            wt.propose_entity_merge(
                ctx,
                keep_id=matched.id,
                drop_id=cand.id,
                reason=f"Fuzzy alias match >= {threshold}",
            )
            dropped.append(cand.id)
        else:
            kept.append(cand)
            for nm in [cand.canonical_name, *cand.aliases]:
                if nm.strip():
                    exact_idx.setdefault(strip_honorifics(nm).lower(), cand)
    return dropped


def deduplicate_entities_fuzzy(repo: Repo, threshold: float = 88.0) -> list[str]:
    """Deterministically merge duplicate Entities (including cross-type character/object duplicates)."""
    ctx = ToolContext(repo=repo, role=Role.SCRIPT_SUPERVISOR, cfg=None)  # type: ignore[arg-type]
    dropped: list[str] = []
    for et in (EntityType.CHARACTER, EntityType.LOCATION, EntityType.OBJECT):
        dropped.extend(
            _merge_within_type(ctx, repo.list_entities(entity_type=et), threshold)
        )

    chars = repo.list_entities(entity_type=EntityType.CHARACTER)
    char_idx = {
        strip_honorifics(nm).lower(): ch
        for ch in chars
        for nm in [ch.canonical_name, *ch.aliases]
        if nm.strip()
    }
    for obj in repo.list_entities(entity_type=EntityType.OBJECT):
        matched = _find_matching_entity(obj, chars, char_idx, threshold)
        if matched is not None:
            wt.propose_entity_merge(
                ctx,
                keep_id=matched.id,
                drop_id=obj.id,
                reason="Object duplicates Character entity",
            )
            dropped.append(obj.id)
    return dropped


def _detect_single_wardrobe_chars(events: list[EventDraft]) -> dict[str, str]:
    """Identify characters that only ever wear a single non-default wardrobe label."""
    wearing_by_char: dict[str, list[str]] = {}
    for ev in events:
        for ef in ev.effects:
            if ef.attribute == "wearing" and ef.new_value:
                cid = normalize_entity_id(ef.entity_id, EntityType.CHARACTER)
                val = ef.new_value.strip()
                if val and val not in wearing_by_char.setdefault(cid, []):
                    wearing_by_char[cid].append(val)
    return {
        cid: labels[0]
        for cid, labels in wearing_by_char.items()
        if len(labels) == 1 and labels[0] != "default"
    }


def _persist_single_entity(
    ctx: ToolContext,
    ent: ExtractedEntityDraft,
    span: tuple[int, int],
    single_wardrobe: dict[str, str],
) -> None:
    """Normalize and store a single extracted entity draft."""
    etype = ent.entity_type
    cname = normalize_indian_epic_names(ent.canonical_name)
    if etype == EntityType.OBJECT and "jatayu" in cname.lower():
        etype = EntityType.CHARACTER
    prefix = (
        "char"
        if etype == EntityType.CHARACTER
        else ("loc" if etype == EntityType.LOCATION else "obj")
    )
    raw_id = (
        ent.entity_id
        if ent.entity_id.startswith(f"{prefix}_")
        else slug_id(cname or ent.entity_id, prefix)
    )
    eid = normalize_entity_id(raw_id, etype)
    if eid.startswith("char_"):
        etype = EntityType.CHARACTER
    attrs = {
        kv.key: AttributeVal(
            value=normalize_indian_epic_names(kv.value),
            provenance=Provenance.FROM_TEXT,
            source_span=span,
        )
        for kv in ent.attributes
        if kv.key
    }
    if eid in single_wardrobe and "wardrobe" not in attrs:
        attrs["wardrobe"] = AttributeVal(
            value=single_wardrobe[eid],
            provenance=Provenance.FROM_TEXT,
            source_span=span,
        )
    wt.put_entity(
        ctx,
        entity_id=eid,
        entity_type=etype,
        canonical_name=cname,
        aliases=[normalize_indian_epic_names(a) for a in ent.aliases if a.strip()],
        attributes=attrs,
    )


def _persist_supervisor_entities(
    ctx: ToolContext,
    entities: list[ExtractedEntityDraft],
    story_text: str,
    single_wardrobe: dict[str, str],
) -> None:
    """Persist all extracted entity drafts from `SCRIPT_SUPERVISOR`."""
    span = (0, min(len(story_text), 64))
    for ent in entities:
        _persist_single_entity(ctx, ent, span, single_wardrobe)


def _ensure_required_entities(
    ctx: ToolContext, default_entities: list[ExtractedEntityDraft]
) -> None:
    """Ensure every scene location and at least one character/object entity exist."""
    for sc in ctx.repo.list_scenes():
        if not ctx.repo.get_entity(sc.location_id):
            title = sc.location_id.replace("loc_", "").replace("_", " ").title()
            attrs = {
                "heading": AttributeVal(
                    value=sc.heading, provenance=Provenance.FROM_TEXT
                )
            }
            wt.put_entity(
                ctx,
                entity_id=sc.location_id,
                entity_type=EntityType.LOCATION,
                canonical_name=title,
                aliases=[],
                attributes=attrs,
            )
    for et in (EntityType.CHARACTER, EntityType.OBJECT):
        if not ctx.repo.list_entities(entity_type=et):
            for de in default_entities:
                if de.entity_type == et:
                    wt.put_entity(
                        ctx,
                        entity_id=de.entity_id,
                        entity_type=et,
                        canonical_name=de.canonical_name,
                        aliases=de.aliases,
                    )


def _create_fallback_scene_event(
    ctx: ToolContext, sc: Scene, base_order: int, all_chars: list[Entity]
) -> None:
    """Create a default scene Event when a scene has no events attached."""
    sc_text = f"{sc.heading} {sc.summary}".lower()
    participants = [
        c.id
        for c in all_chars
        if any(
            nm.lower() in sc_text
            for nm in [c.canonical_name, *c.aliases, strip_honorifics(c.canonical_name)]
            if nm.strip()
        )
    ] or [c.id for c in all_chars[:2]]
    fx = [
        StateEffect(entity_id=cid, attribute="location", new_value=sc.location_id)
        for cid in participants
    ] + [
        StateEffect(entity_id=cid, attribute="wearing", new_value="default")
        for cid in participants
    ]
    wt.put_event(
        ctx,
        event_id=f"evt_{sc.id}",
        story_order=base_order,
        scene_id=sc.id,
        summary=sc.summary or sc.heading,
        participants=participants,
        effects=fx,
    )


def _enrich_single_event(
    ctx: ToolContext,
    sc: Scene,
    ev: Event,
    order: int,
    all_chars: list[Entity],
    valid_cids: set[str],
    valid_oids: set[str],
    single_wardrobe: dict[str, str],
) -> None:
    """Ensure a scene Event has complete location and wearing StateEffects for all participants."""
    new_fx = _normalize_event_effects(ev.effects, single_wardrobe, sc.location_id)
    existing_pairs = {(ef.entity_id, ef.attribute) for ef in new_fx}
    fx_cids = [ef.entity_id for ef in new_fx if ef.entity_id in valid_cids]
    participants = list(
        dict.fromkeys([p for p in [*ev.participants, *fx_cids] if p in valid_cids])
    ) or [c.id for c in all_chars[:2]]
    for cid in participants:
        if (cid, "location") not in existing_pairs:
            new_fx.append(
                StateEffect(
                    entity_id=cid, attribute="location", new_value=sc.location_id
                )
            )
        if (cid, "wearing") not in existing_pairs:
            new_fx.append(
                StateEffect(entity_id=cid, attribute="wearing", new_value="default")
            )
    ref_oids = (
        {ef.entity_id for ef in new_fx if ef.entity_id in valid_oids}
        | {
            ef.new_value
            for ef in new_fx
            if ef.attribute == "holding" and ef.new_value in valid_oids
        }
        | {p for p in ev.participants if p in valid_oids}
    )
    for oid in ref_oids:
        if (oid, "location") not in existing_pairs:
            new_fx.append(
                StateEffect(
                    entity_id=oid, attribute="location", new_value=sc.location_id
                )
            )
    wt.put_event(
        ctx,
        event_id=ev.id,
        story_order=order,
        scene_id=sc.id,
        summary=normalize_indian_epic_names(ev.summary or sc.summary or sc.heading),
        participants=participants,
        effects=new_fx,
    )


def _enrich_scene_event(
    ctx: ToolContext,
    sc: Scene,
    idx: int,
    sc_events: list[Event],
    all_chars: list[Entity],
    all_objs: list[Entity],
    single_wardrobe: dict[str, str],
) -> None:
    """Enrich or synthesize chronological Events for scene `sc`."""
    base_order = idx * 10
    if not sc_events:
        _create_fallback_scene_event(ctx, sc, base_order, all_chars)
        return
    valid_cids = {c.id for c in all_chars}
    valid_oids = {o.id for o in all_objs}
    all_sc_p = [p for e in sc_events for p in e.participants]
    for e_idx, ev in enumerate(sc_events):
        ev_in = (
            ev.model_copy(update={"participants": [*ev.participants, *all_sc_p]})
            if e_idx == 0 and len(sc_events) > 1
            else ev
        )
        _enrich_single_event(
            ctx,
            sc,
            ev_in,
            base_order + e_idx,
            all_chars,
            valid_cids,
            valid_oids,
            single_wardrobe,
        )


def _invoke_supervisor_role(
    ctx: ToolContext,
    story_text: str,
    default_entities: list[ExtractedEntityDraft],
    default_events: list[EventDraft],
    mock_llm: MockLLMClient | None,
) -> RoleRunResult:
    """Build prompt context and invoke `SCRIPT_SUPERVISOR` via `run_role`."""
    scenes_ctx = [
        {
            "scene_id": s.id,
            "location_id": s.location_id,
            "heading": s.heading,
            "summary": s.summary,
        }
        for s in ctx.repo.list_scenes()
    ]
    events_ctx = [
        {
            "event_id": e.id,
            "story_order": e.story_order,
            "scene_id": e.scene_id,
            "summary": e.summary,
            "participants": e.participants,
        }
        for e in ctx.repo.list_events()
    ]
    prompt = (
        "Extract all canonical Entities (`character`, `location`, `object`) and chronological Event state transitions.\n"
        f"1. Existing scenes from STORY_ARCHITECT: {scenes_ctx}\n"
        f"2. Existing events from STORY_ARCHITECT: {events_ctx}\n"
        "3. Create a `location` entity for EVERY `location_id` used in the scenes above.\n"
        "4. Use authentic Hindi character names (`Ram`, `Sita`, `Lakshman`, `Shurpanakha`, `Ravan`, `Jatayu`, `Shabari`). Never classify sentient beings like Jatayu as `object`.\n"
        "5. List ONLY the characters participating in each scene event, and use `wearing='default'` unless a character changes outfits across scenes.\n\n"
        f"STORY:\n{story_text}"
    )
    return run_role(
        role=Role.SCRIPT_SUPERVISOR,
        ctx=ctx,
        user_prompt=prompt,
        output_schema=ScriptSupervisorOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: ScriptSupervisorOutput(
            entities=default_entities, events=default_events
        ),
    )


def run_script_supervisor(
    ctx: ToolContext,
    story_text: str,
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run SCRIPT_SUPERVISOR (`script_supervisor_agent`) to canonicalize Characters, Locations, Objects, and StateEffects."""
    story_text = normalize_indian_epic_names(story_text)
    default_entities, _, default_events = extract_entities_from_story(story_text)
    res = _invoke_supervisor_role(
        ctx, story_text, default_entities, default_events, mock_llm
    )
    out: ScriptSupervisorOutput = res.output
    single_wardrobe = _detect_single_wardrobe_chars(
        list(out.events) if out.events else list(default_events)
    )
    _persist_supervisor_entities(
        ctx, out.entities or default_entities, story_text, single_wardrobe
    )
    for ev in out.events:
        wt.put_event(
            ctx,
            event_id=ev.event_id,
            story_order=ev.story_order,
            scene_id=ev.scene_id,
            summary=normalize_indian_epic_names(ev.summary),
            participants=list(
                dict.fromkeys(normalize_entity_id(p) for p in ev.participants)
            ),
            effects=_normalize_event_effects(ev.effects, single_wardrobe),
        )

    deduplicate_entities_fuzzy(ctx.repo)
    _ensure_required_entities(ctx, default_entities)
    all_chars = ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    all_objs = ctx.repo.list_entities(entity_type=EntityType.OBJECT)
    existing_events = ctx.repo.list_events()
    for idx, sc in enumerate(ctx.repo.list_scenes(), start=1):
        sc_events = [e for e in existing_events if e.scene_id == sc.id]
        _enrich_scene_event(
            ctx, sc, idx, sc_events, all_chars, all_objs, single_wardrobe
        )
    rebuild_state_facts(ctx.repo)
    return res
