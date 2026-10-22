"""Implicit scene-entry relocation: who is placed at a scene's location when the scene opens.

Screenplays rarely narrate every walk between scenes, so a character who appears in the
next scene at a new location would otherwise still be "at" the previous one. Rule (general,
story-agnostic): every character present in a scene is relocated to the scene's location
at the scene's entry order, *unless an explicit Event in the scene moves them* and they are
not on screen before that Event (their entrance is then narrated by the Event itself).

"On screen before Event e" means: the character participates in an earlier Event of the
scene, or is cast in one of the scene's shots that opens before e and does not play e.
Objects held by a relocated character travel with them.

The entry order is the post-state order just before the scene's first Event
(`first_order - 1`, the same order clip windows open at). If that order belongs to an Event
of another scene (band overflow), the entry falls back to the first Event's order and is
applied before that Event's own effects.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schema import Entity, EntityType, Event, Scene, Shot


@dataclass(frozen=True)
class SceneEntry:
    """Typed contract: relocate `cast` to `location_id` at `order` (before Events there)."""

    scene_id: str
    location_id: str
    order: int
    cast: tuple[str, ...]

    @property
    def cause(self) -> str:
        """Synthetic `StateFact.caused_by_event_id` for facts this entry opens."""
        return f"scene_entry:{self.scene_id}"


def is_scene_entry_cause(cause: str) -> bool:
    """True when a StateFact was synthesized by an implicit scene entry."""
    return cause.startswith("scene_entry:")


def _first_location_event(char_id: str, events: list[Event]) -> Event | None:
    return next(
        (
            ev
            for ev in events
            if any(
                f.entity_id == char_id and f.attribute == "location" for f in ev.effects
            )
        ),
        None,
    )


def _on_screen_before(
    char_id: str, explicit: Event, events: list[Event], shots: list[Shot]
) -> bool:
    if any(
        char_id in ev.participants
        for ev in events
        if ev.story_order < explicit.story_order
    ):
        return True
    return any(
        sh.story_order < explicit.story_order
        and explicit.id not in sh.covers_event_ids
        and any(c.entity_id == char_id for c in sh.cast)
        for sh in shots
    )


def _scene_cast(
    sc: Scene, events: list[Event], shots: list[Shot], chars: frozenset[str]
) -> list[str]:
    """Characters present in the scene (events, steps, shots), in first-mention order."""
    ids = [p for ev in events for p in ev.participants]
    ids += [s.actor_id for s in sc.interaction_steps]
    ids += [s.target_id for s in sc.interaction_steps if s.target_id]
    ids += [c.entity_id for sh in shots for c in sh.cast]
    return [i for i in dict.fromkeys(ids) if i in chars]


def _relocated(
    sc: Scene, events: list[Event], shots: list[Shot], chars: frozenset[str]
) -> tuple[str, ...]:
    out: list[str] = []
    for cid in _scene_cast(sc, events, shots, chars):
        explicit = _first_location_event(cid, events)
        if explicit is None or _on_screen_before(cid, explicit, events, shots):
            out.append(cid)
    return tuple(out)


def _entry_order(sc: Scene, events: list[Event], owners: dict[int, set[str]]) -> int:
    first = events[0].story_order if events else sc.index * 10
    taken = any(s != sc.id for s in owners.get(first - 1, set()))
    return first if events and taken else first - 1


def plan_scene_entries(
    scenes: list[Scene],
    events: list[Event],
    shots: list[Shot],
    entities: list[Entity],
) -> list[SceneEntry]:
    """One `SceneEntry` per located scene, sorted by entry order (O(S + E + shots·cast))."""
    chars = frozenset(e.id for e in entities if e.entity_type == EntityType.CHARACTER)
    by_scene: dict[str, list[Event]] = {}
    owners: dict[int, set[str]] = {}
    for ev in sorted(events, key=lambda e: (e.story_order, e.id)):
        by_scene.setdefault(ev.scene_id, []).append(ev)
        owners.setdefault(ev.story_order, set()).add(ev.scene_id)
    shots_by_scene: dict[str, list[Shot]] = {}
    for sh in shots:
        shots_by_scene.setdefault(sh.scene_id, []).append(sh)
    out: list[SceneEntry] = []
    for sc in scenes:
        if not sc.location_id:
            continue
        sc_events = by_scene.get(sc.id, [])
        cast = _relocated(sc, sc_events, shots_by_scene.get(sc.id, []), chars)
        order = _entry_order(sc, sc_events, owners)
        out.append(SceneEntry(sc.id, sc.location_id, order, cast))
    return sorted(out, key=lambda e: e.order)
