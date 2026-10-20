"""Scoped read views (`ShotView`, `SceneView`, `OutlineView`, `EntityDesignView`) for agents and compilers."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .anchors.chaining import resolve_chain_frame
from .errors import NotFound
from .repo import Repo
from .schema import (
    Appearance,
    Asset,
    DialogueLine,
    Entity,
    Event,
    GenerationRun,
    MusicCue,
    Scene,
    Shot,
    Status,
    StyleGuide,
)
from .state import window_states
from .timeline.clip_context import ClipContext, clip_context
from .timeline.prop_state import resolve_prop_states_for_shot


class OutlineView(BaseModel):
    style_guide: StyleGuide | None = None
    entities: list[Entity] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)


class EntityDesignView(BaseModel):
    style_guide: StyleGuide | None = None
    entity: Entity
    appearances: list[Appearance] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    required_state_labels: list[str] = Field(default_factory=list)


class SceneView(BaseModel):
    style_guide: StyleGuide | None = None
    scene: Scene
    location: Entity | None = None
    location_appearance: Appearance | None = None
    events: list[Event] = Field(default_factory=list)
    entities_in_scene: list[Entity] = Field(default_factory=list)
    dialogue_lines: list[DialogueLine] = Field(default_factory=list)
    music_cues: list[MusicCue] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)


class ShotView(BaseModel):
    style_guide: StyleGuide
    scene: Scene
    shot: Shot
    location: Entity
    location_appearance: Appearance
    location_assets: list[Asset] = Field(default_factory=list)
    cast_entities: dict[str, Entity] = Field(default_factory=dict)
    cast_appearances: dict[str, Appearance] = Field(default_factory=dict)
    cast_assets: dict[str, list[Asset]] = Field(default_factory=dict)
    cast_states: dict[str, dict[str, str]] = Field(default_factory=dict)  # clip opening
    cast_end_states: dict[str, dict[str, str]] = Field(
        default_factory=dict
    )  # clip closing
    prop_entities: dict[str, Entity] = Field(default_factory=dict)
    prop_appearances: dict[str, Appearance] = Field(default_factory=dict)
    prop_assets: dict[str, list[Asset]] = Field(default_factory=dict)
    prop_states: dict[str, dict[str, str]] = Field(default_factory=dict)
    dialogue_lines: list[DialogueLine] = Field(default_factory=list)
    music_cue: MusicCue | None = None
    prev_shot_last_frame: Asset | None = None


def outline_view(repo: Repo) -> OutlineView:
    return OutlineView(
        style_guide=repo.get_style_guide(),
        entities=repo.list_entities(),
        scenes=repo.list_scenes(),
        events=repo.list_events(),
    )


def entity_design_view(repo: Repo, entity_id: str) -> EntityDesignView:
    ent = repo.get_entity(entity_id)
    if not ent:
        raise NotFound(f"Entity {entity_id} not found")
    apps = repo.list_appearances(entity_id=entity_id, active_only=True)
    assets: list[Asset] = []
    seen_aids: set[str] = set()
    for a in apps:
        for aid in a.asset_ids:
            if aid not in seen_aids:
                asset = repo.get_asset(aid)
                if asset:
                    assets.append(asset)
                    seen_aids.add(aid)

    wearing_labels: list[str] = []
    for sf in repo.list_state_facts(entity_id=entity_id):
        if sf.attribute == "wearing" and sf.value and sf.value not in wearing_labels:
            wearing_labels.append(sf.value)
    labels = wearing_labels if wearing_labels else ["default"]

    return EntityDesignView(
        style_guide=repo.get_style_guide(),
        entity=ent,
        appearances=apps,
        assets=assets,
        required_state_labels=labels,
    )


def scene_view(repo: Repo, scene_id: str) -> SceneView:
    scene = repo.get_scene(scene_id)
    if not scene:
        raise NotFound(f"Scene {scene_id} not found")
    loc = repo.get_entity(scene.location_id) if scene.location_id else None
    loc_apps = (
        repo.list_appearances(entity_id=scene.location_id) if scene.location_id else []
    )
    events = repo.list_events(scene_id=scene_id)
    participant_ids: set[str] = set()
    for ev in events:
        participant_ids.update(ev.participants)
        for eff in ev.effects:
            participant_ids.add(eff.entity_id)
    entities = [
        e for eid in sorted(participant_ids) if (e := repo.get_entity(eid)) is not None
    ]
    return SceneView(
        style_guide=repo.get_style_guide(),
        scene=scene,
        location=loc,
        location_appearance=loc_apps[-1] if loc_apps else None,
        events=events,
        entities_in_scene=entities,
        dialogue_lines=repo.list_dialogue(scene_id=scene_id),
        music_cues=repo.list_music_cues(scene_id=scene_id),
        shots=repo.list_shots(scene_id=scene_id),
    )


def _resolve_cast_for_shot(
    repo: Repo, shot: Shot
) -> tuple[dict[str, Entity], dict[str, Appearance], dict[str, list[Asset]]]:
    cast_entities: dict[str, Entity] = {}
    cast_appearances: dict[str, Appearance] = {}
    cast_assets: dict[str, list[Asset]] = {}
    for c in shot.cast:
        ent = repo.get_entity(c.entity_id)
        if ent:
            cast_entities[c.entity_id] = ent
        app = repo.get_appearance(c.appearance_id) if c.appearance_id else None
        if not app:
            apps = repo.list_appearances(entity_id=c.entity_id)
            app = apps[-1] if apps else None
        if app:
            cast_appearances[c.entity_id] = app
            cast_assets[c.entity_id] = [
                a for aid in app.asset_ids if (a := repo.get_asset(aid)) is not None
            ]
    return cast_entities, cast_appearances, cast_assets


def _resolve_props_for_shot(
    repo: Repo, shot: Shot
) -> tuple[dict[str, Entity], dict[str, Appearance], dict[str, list[Asset]]]:
    prop_entities: dict[str, Entity] = {}
    prop_appearances: dict[str, Appearance] = {}
    prop_assets: dict[str, list[Asset]] = {}
    for pid in shot.prop_ids:
        pent = repo.get_entity(pid)
        if pent:
            prop_entities[pid] = pent
        paid = shot.prop_appearance_ids.get(pid, "")
        papp = repo.get_appearance(paid) if paid else None
        if not papp:
            papps = repo.list_appearances(entity_id=pid)
            papp = papps[-1] if papps else None
        if papp:
            prop_appearances[pid] = papp
            prop_assets[pid] = [
                a for aid in papp.asset_ids if (a := repo.get_asset(aid)) is not None
            ]
    return prop_entities, prop_appearances, prop_assets


def generation_run_rank(r: GenerationRun) -> tuple[int, int, float, int]:
    """Return a deterministic comparison tuple ranking `GenerationRun` quality (higher is better)."""
    is_approved = 1 if r.status == Status.APPROVED else 0
    sc = r.qa_scores
    if sc is None:
        return (is_approved, 1, 0.0, int(r.attempt))
    bad_frame = bool(
        {"style_drift", "frozen_frame", "start_frame_bleed"} & set(sc.artifact_flags)
    )
    quality = (
        float(sc.physics_plausibility)
        + float(sc.object_permanence)
        + float(sc.action_achieved)
        + float(sc.setting_match)
        + float(sc.wardrobe_match)
        - 0.25 * len(sc.artifact_flags)
    )
    return (is_approved, 0 if bad_frame else 1, round(quality, 4), int(r.attempt))


def _resolve_prev_shot_last_frame(repo: Repo, shot: Shot) -> Asset | None:
    return resolve_chain_frame(repo, shot)


def _resolve_shot_location(
    repo: Repo, shot: Shot
) -> tuple[Entity, Appearance, list[Asset]]:
    loc = repo.get_entity(shot.location_id)
    if not loc:
        raise NotFound(f"Location entity {shot.location_id} not found")
    loc_app = repo.get_appearance(shot.location_appearance_id)
    if not loc_app:
        apps = repo.list_appearances(entity_id=shot.location_id)
        if not apps:
            raise NotFound(f"Location appearance for {shot.location_id} not found")
        loc_app = apps[-1]
    loc_assets = [
        a for aid in loc_app.asset_ids if (a := repo.get_asset(aid)) is not None
    ]
    return loc, loc_app, loc_assets


def _with_state_appearances(repo: Repo, view: ShotView) -> ShotView:
    """Swap in the appearance matching each entity's opening visual state (if minted)."""
    from .anchors.visual_states import resolve_state_refs  # imports views: avoid cycle

    refs = resolve_state_refs(repo, view)
    if not refs:
        return view
    cast = {**view.cast_appearances}
    props = {**view.prop_appearances}
    for eid, ref in refs.items():
        (props if eid in view.shot.prop_ids else cast)[eid] = ref.appearance
    return view.model_copy(update={"cast_appearances": cast, "prop_appearances": props})


def _clip_scoped_shot(shot: Shot, ctx: ClipContext) -> Shot:
    """The shot as it renders its clip: clip Events, opening order and per-clip props."""
    if not ctx.has_clip:
        return shot
    return shot.model_copy(
        update={
            "prop_ids": list(ctx.prop_ids),
            "covers_event_ids": list(ctx.window.event_ids),
            "story_order": ctx.window.first_order,
        }
    )


def shot_view(repo: Repo, shot_id: str) -> ShotView:
    stored = repo.get_shot(shot_id)
    if not stored:
        raise NotFound(f"Shot {shot_id} not found")
    scene = repo.get_scene(stored.scene_id)
    if not scene:
        raise NotFound(f"Scene {stored.scene_id} not found")
    sg = repo.get_style_guide()
    if not sg:
        raise NotFound("StyleGuide not found")
    ctx = clip_context(repo, scene, stored)
    shot = _clip_scoped_shot(stored, ctx)
    loc, loc_app, loc_assets = _resolve_shot_location(repo, shot)
    c_ents, c_apps, c_assets = _resolve_cast_for_shot(repo, shot)
    c_open, c_close = window_states(repo, [c.entity_id for c in shot.cast], ctx.window)
    p_ents, p_apps, p_assets = _resolve_props_for_shot(repo, shot)
    dlines = [
        d for did in shot.dialogue_ids if (d := repo.get_dialogue(did)) is not None
    ]
    mcue = repo.get_music_cue(shot.music_cue_id) if shot.music_cue_id else None
    view = ShotView(
        style_guide=sg,
        scene=scene,
        shot=shot,
        location=loc,
        location_appearance=loc_app,
        location_assets=loc_assets,
        cast_entities=c_ents,
        cast_appearances=c_apps,
        cast_assets=c_assets,
        cast_states=c_open,
        cast_end_states=c_close,
        prop_entities=p_ents,
        prop_appearances=p_apps,
        prop_assets=p_assets,
        prop_states=resolve_prop_states_for_shot(
            repo, scene, shot, ctx.window, ctx.lifecycles
        ),
        dialogue_lines=dlines,
        music_cue=mcue,
        prev_shot_last_frame=_resolve_prev_shot_last_frame(repo, stored),
    )
    return _with_state_appearances(repo, view)
