"""Resolve a `PlanInput` for one shot from the StoryGraph (read-only).

Beats come from the clip's interaction steps (seconds allocated by `duration_hint_s`);
graph snapshots are read with `state_at` at the clip opening order, after each beat's
aligned Events (`timeline.clip_events.scene_step_events`) and at the clip closing order, so
the plan's first/last second match the clip window exactly. Wardrobe comes from the
resolved Appearance, identity sheets from the Appearance's Assets.
"""

from __future__ import annotations

from ...clips.models import ClipScript
from ...errors import ValidationFailed
from ...repo import Repo
from ...schema import Appearance, Entity, EntityType, InteractionStep, Scene, Shot
from ...state import appearance_for, state_at
from ...timeline.clip_context import clip_steps_of
from ...timeline.clip_events import ClipWindow, scene_clip_windows, scene_step_events
from .models import (
    BeatSpan,
    CameraInput,
    CastInput,
    ObjectInput,
    PlanInput,
    StateSnapshot,
)
from .permanence import backfill_established
from .timing import allocate_spans


def _appearance(
    repo: Repo, entity_id: str, app_id: str, order: int
) -> Appearance | None:
    found = repo.get_appearance(app_id) if app_id else None
    if found is not None:
        return found
    try:
        return appearance_for(repo, entity_id, order)
    except ValidationFailed:  # entity has no appearance yet -> no identity ref
        return None


def _ref(repo: Repo, app: Appearance | None) -> tuple[str | None, str | None]:
    """(asset id, uri) of the first stored sheet of `app`."""
    for aid in app.asset_ids if app else []:
        asset = repo.get_asset(aid)
        if asset is not None and asset.uri:
            return asset.id, asset.uri
    return None, None


def _cast(repo: Repo, shot: Shot, names: dict[str, Entity]) -> list[CastInput]:
    out: list[CastInput] = []
    for c in shot.cast:
        if c.position == "offscreen_voice" or c.entity_id not in names:
            continue
        app = _appearance(repo, c.entity_id, c.appearance_id, shot.story_order)
        aid, uri = _ref(repo, app)
        out.append(
            CastInput(
                entity_id=c.entity_id,
                name=names[c.entity_id].canonical_name,
                wardrobe=(app.wardrobe or app.state_label) if app else "default",
                description=app.visual_description if app else "",
                appearance_id=app.id if app else "",
                ref_asset_id=aid,
                ref_uri=uri,
                position=c.position,
            )
        )
    return out


def _objects(
    repo: Repo, shot: Shot, objects: list[Entity], focus: set[str]
) -> list[ObjectInput]:
    out: list[ObjectInput] = []
    for obj in objects:
        app_id = shot.prop_appearance_ids.get(obj.id, "")
        app = _appearance(repo, obj.id, app_id, shot.story_order)
        aid, uri = _ref(repo, app)
        out.append(
            ObjectInput(
                entity_id=obj.id,
                name=obj.canonical_name,
                description=app.visual_description if app else "",
                ref_asset_id=aid,
                ref_uri=uri,
                focus=obj.id in focus,
            )
        )
    return out


def _beats(steps: tuple[InteractionStep, ...], duration: float) -> list[BeatSpan]:
    spans = allocate_spans([s.duration_hint_s for s in steps], duration)
    return [
        BeatSpan(
            index=i,
            t_start=start,
            t_end=end,
            actor_id=s.actor_id,
            target_id=s.target_id,
            action=s.action or s.description,
            pre_state=s.pre_state,
            post_state=s.post_state,
        )
        for i, (s, (start, end)) in enumerate(zip(steps, spans, strict=True))
    ]


def _snapshot_orders(
    win: ClipWindow,
    steps: tuple[InteractionStep, ...],
    by_step: dict[int, list[str]],
    order_of: dict[str, int],
) -> list[int]:
    """Opening order, the order after each beat's Events, then the closing order."""
    orders = [win.open_at]
    for step in steps:
        ev_orders = [
            order_of[e] for e in by_step.get(step.step_index, []) if e in order_of
        ]
        orders.append(max([orders[-1], *ev_orders]))
    orders[-1] = win.close_at
    return orders


def _snapshots(repo: Repo, ids: list[str], orders: list[int]) -> list[StateSnapshot]:
    return [
        StateSnapshot(order=o, states={eid: state_at(repo, eid, o) for eid in ids})
        for o in orders
    ]


def _location(repo: Repo, shot: Shot) -> tuple[str, str, str | None, str | None]:
    ent = repo.get_entity(shot.location_id)
    app = _appearance(
        repo, shot.location_id, shot.location_appearance_id, shot.story_order
    )
    aid, uri = _ref(repo, app)
    name = ent.canonical_name if ent else shot.location_id
    return name, app.visual_description if app else "", aid, uri


def _style(repo: Repo) -> str:
    sg = repo.get_style_guide()
    return f"{sg.visual_medium}; {sg.lighting_rules}" if sg else ""


def build_plan_input(
    repo: Repo, scene: Scene, shot: Shot, prompt_version_id: str = ""
) -> PlanInput:
    """Graph-resolved `PlanInput` for `shot` (its clip in `scene`)."""
    clip: ClipScript | None = next(
        (c for c in scene.clips if c.clip_index == shot.clip_index), None
    )
    if clip is None:
        raise ValueError(f"shot {shot.id} has no screenwriter clip in {scene.id}")
    events = repo.list_events(scene_id=scene.id)
    win = scene_clip_windows(scene, events)[clip.clip_index]
    steps = clip_steps_of(scene, clip)
    entities = repo.list_entities()
    names = {e.id: e for e in entities}
    objects = [e for e in entities if e.entity_type == EntityType.OBJECT]
    focus = set(shot.prop_ids) | {s.target_id for s in steps if s.target_id}
    order_of = {e.id: e.story_order for e in events}
    orders = _snapshot_orders(win, steps, scene_step_events(scene, events), order_of)
    tracked = [e.id for e in entities if e.entity_type != EntityType.LOCATION]
    loc_name, loc_desc, loc_aid, loc_uri = _location(repo, shot)
    return PlanInput(
        project_id=str(getattr(repo.store, "project_id", "")),
        scene_id=scene.id,
        shot_id=shot.id,
        clip_index=clip.clip_index,
        duration_s=clip.duration_s or shot.duration_s,
        location_id=shot.location_id,
        location_name=loc_name,
        location_description=loc_desc,
        location_ref_asset_id=loc_aid,
        location_ref_uri=loc_uri,
        time_of_day=scene.time_of_day,
        style=_style(repo),
        camera=CameraInput.model_validate(shot.camera.model_dump()),
        cast=_cast(repo, shot, names),
        objects=_objects(repo, shot, objects, focus),
        beats=_beats(steps, clip.duration_s or shot.duration_s),
        snapshots=backfill_established(
            _snapshots(repo, tracked, orders), [o.id for o in objects], shot.location_id
        ),
        prompt_version_id=prompt_version_id,
    )
