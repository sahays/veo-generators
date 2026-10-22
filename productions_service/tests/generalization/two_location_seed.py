"""Story-agnostic two-location fixture: a hero and a helper walk from a glade to a stream.

Scene 1 (glade) places both characters with an explicit Event. Scene 2 (stream) narrates
NO move: its first clip plays no Event (the p-og5klsx9 / p-pzbfjudf incident shape), its
second clip plays the scene's Events. An optional third character enters scene 2 via an
explicit Event in clip 2 only.
"""

from __future__ import annotations

from storygraph.repo import Repo
from storygraph.schema import (
    CastInShot,
    ClipScript,
    Entity,
    EntityType,
    Event,
    InteractionStep,
    Role,
    Scene,
    Shot,
    StateEffect,
)
from storygraph.state import rebuild_state_facts

HERO, HELPER, GUEST = "char_hero", "char_helper", "char_guest"
GLADE, STREAM, LANTERN = "loc_glade", "loc_stream", "obj_lantern"
_ACTIONS = (
    "kneels to inspect fresh tracks in the mud",
    "raises the lantern toward the canopy",
    "splashes water onto a dusty face",
    "points across the ripples at a heron",
)


def _entities(repo: Repo) -> None:
    for eid, etype, name in (
        (HERO, EntityType.CHARACTER, "Hero"),
        (HELPER, EntityType.CHARACTER, "Helper"),
        (GUEST, EntityType.CHARACTER, "Guest"),
        (GLADE, EntityType.LOCATION, "Glade"),
        (STREAM, EntityType.LOCATION, "Stream"),
        (LANTERN, EntityType.OBJECT, "Lantern"),
    ):
        repo.put_entity(
            Entity(
                id=eid,
                created_by=Role.SCRIPT_SUPERVISOR,
                entity_type=etype,
                canonical_name=name,
            )
        )


def _event(
    eid: str,
    order: int,
    scene: str,
    who: list[str],
    effs: list[tuple[str, str, str | None]],
) -> Event:
    return Event(
        id=eid,
        created_by=Role.SCRIPT_SUPERVISOR,
        story_order=order,
        scene_id=scene,
        summary=f"{eid} beat",
        participants=who,
        effects=[
            StateEffect(entity_id=e, attribute=a, new_value=v) for e, a, v in effs
        ],
    )


def _scene(
    sid: str, index: int, loc: str, actors: list[str], clips: list[list[int]]
) -> Scene:
    steps = [
        InteractionStep(
            step_index=i + 1,
            actor_id=a,
            interaction_type="environment",
            target_id=loc,
            action=_ACTIONS[(index + i) % len(_ACTIONS)],
        )
        for i, a in enumerate(actors)
    ]
    return Scene(
        id=sid, created_by=Role.STORY_ARCHITECT, index=index, heading=sid, location_id=loc,
        time_of_day="day", interaction_steps=steps,
        clips=[ClipScript(clip_index=n + 1, step_indices=s, omni_prompt="beat") for n, s in enumerate(clips)],
    )  # fmt: skip


def _shot(sid: str, scene: str, idx: int, loc: str, cast: list[str]) -> Shot:
    return Shot(
        id=sid, created_by=Role.DIRECTOR, scene_id=scene, index_in_scene=idx, story_order=0,
        duration_s=8.0, clip_index=idx, location_id=loc,
        cast=[CastInShot(entity_id=c, position=p) for c, p in zip(cast, ("left", "right", "center"), strict=False)],
    )  # fmt: skip


def seed_two_locations(repo: Repo, guest_enters: bool = False) -> None:
    """Seed the fixture and rebuild state facts."""
    _entities(repo)
    repo.put_scene(_scene("scn_1", 1, GLADE, [HERO, HELPER], [[1, 2]]))
    repo.put_scene(_scene("scn_2", 2, STREAM, [HERO, HELPER], [[1], [2]]))
    place = [
        (HERO, "location", GLADE),
        (HELPER, "location", GLADE),
        (HERO, "holding", LANTERN),
        (LANTERN, "location", GLADE),
    ]
    repo.put_event(_event("evt_1", 10, "scn_1", [HERO, HELPER], place))
    repo.put_event(
        _event("evt_2", 20, "scn_2", [HELPER], [(HELPER, "mood", "curious")])
    )
    s2_cast = [HERO, HELPER]
    if guest_enters:
        repo.put_event(
            _event("evt_0", 5, "scn_1", [GUEST], [(GUEST, "location", GLADE)])
        )
        repo.put_event(
            _event("evt_3", 21, "scn_2", [GUEST], [(GUEST, "location", STREAM)])
        )
    repo.put_shot(_shot("shot_1", "scn_1", 1, GLADE, [HERO, HELPER]))
    repo.put_shot(_shot("shot_2_1", "scn_2", 1, STREAM, s2_cast))
    repo.put_shot(
        _shot(
            "shot_2_2",
            "scn_2",
            2,
            STREAM,
            [*s2_cast, GUEST] if guest_enters else s2_cast,
        )
    )
    rebuild_state_facts(repo)
