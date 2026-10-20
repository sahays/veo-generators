"""Per-shot clip context: the clip window, the alive-and-relevant props and lifecycles."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..clips.models import ClipScript
from ..repo import Repo
from ..schema import Entity, EntityType, Event, InteractionStep, Scene, Shot
from ..state import holders_at, state_at
from .clip_events import ClipWindow, scene_clip_windows
from .lifecycle import ClipEvidence, Lifecycle, clip_prop_ids, object_lifecycle


@dataclass(frozen=True)
class ClipContext:
    """Typed contract consumed by `views.shot_view` and the spec linter."""

    window: ClipWindow
    prop_ids: tuple[str, ...]
    lifecycles: dict[str, Lifecycle] = field(default_factory=dict)
    has_clip: bool = True


def clip_steps_of(scene: Scene, clip: ClipScript) -> tuple[InteractionStep, ...]:
    by_index = {s.step_index: s for s in scene.interaction_steps}
    return tuple(by_index[i] for i in dict.fromkeys(clip.step_indices) if i in by_index)


def _scene_evidence(scene: Scene, events: list[Event]) -> list[ClipEvidence]:
    windows = scene_clip_windows(scene, events)
    return [
        ClipEvidence(windows[c.clip_index], c, clip_steps_of(scene, c))
        for c in scene.clips
        if c.clip_index in windows
    ]


def story_lifecycles(
    repo: Repo, objects: list[Entity] | None = None
) -> dict[str, Lifecycle]:
    """Lifecycle for every OBJECT entity across the whole story."""
    objs = (
        objects
        if objects is not None
        else repo.list_entities(entity_type=EntityType.OBJECT)
    )
    events = repo.list_events()
    evidence = [
        ev
        for sc in repo.list_scenes()
        for ev in _scene_evidence(sc, [e for e in events if e.scene_id == sc.id])
    ]
    facts = repo.list_state_facts()
    return {
        o.id: object_lifecycle(
            o, [f for f in facts if f.entity_id == o.id], events, evidence
        )
        for o in objs
    }


def _held_ids(repo: Repo, win: ClipWindow) -> frozenset[str]:
    return frozenset(holders_at(repo, win.open_at)) | frozenset(
        holders_at(repo, win.close_at)
    )


def _placed_ids(repo: Repo, shot: Shot, win: ClipWindow) -> frozenset[str]:
    """Director-listed props whose own facts place them in the set (in frame by state)."""
    keys = ("supported_by", "sub_location")
    return frozenset(
        pid
        for pid in shot.prop_ids
        if any(
            k in state_at(repo, pid, o)
            for o in (win.open_at, win.close_at)
            for k in keys
        )
    )


def clip_context(repo: Repo, scene: Scene, shot: Shot) -> ClipContext:
    """Clip window + per-clip props for `shot` (legacy shots fall back to `story_order`)."""
    clip = next((c for c in scene.clips if c.clip_index == shot.clip_index), None)
    if clip is None:
        legacy = ClipWindow(
            shot.clip_index or 0, (), shot.story_order, shot.story_order
        )
        return ClipContext(legacy, tuple(shot.prop_ids), {}, has_clip=False)
    events = repo.list_events(scene_id=scene.id)
    win = scene_clip_windows(scene, events)[clip.clip_index]
    objects = repo.list_entities(entity_type=EntityType.OBJECT)
    lifecycles = story_lifecycles(repo, objects)
    ev = ClipEvidence(win, clip, clip_steps_of(scene, clip))
    in_clip = [e for e in events if e.id in set(win.event_ids)]
    anchored = _held_ids(repo, win) | _placed_ids(repo, shot, win)
    props = clip_prop_ids(objects, lifecycles, ev, in_clip, anchored)
    return ClipContext(win, tuple(props), lifecycles)
