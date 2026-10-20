"""Replay-shaped fixture for spec-data tests (p-zyt0jprz scene 5: Pip feeds Milo).

Mirrors the live data that failed QA: step text that repeats the actor name ('Pip picks
up ...'), `alive_present='consumed'` (not 'false'), a condition stored as a place
(`sub_location='closed'`), an orientation-only chair ('jolted') and set dressing with no
place facts at all.
"""

from __future__ import annotations

from conftest import seed_valid_graph
from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
    CameraSpec,
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
    Status,
)
from storygraph.state import rebuild_state_facts

PIP, MILO = "char_pip", "char_milo"
BERRY, DOOR, CHAIR, TABLE = "obj_berry", "obj_door", "obj_chair", "obj_table"
SCENE = "scn_9"
_NAMES: tuple[tuple[str, EntityType, str], ...] = (
    (PIP, EntityType.CHARACTER, "Pip"),
    (MILO, EntityType.CHARACTER, "Milo"),
    (BERRY, EntityType.OBJECT, "Strawberry"),
    (DOOR, EntityType.OBJECT, "Blue Door"),
    (CHAIR, EntityType.OBJECT, "Wooden Chair"),
    (TABLE, EntityType.OBJECT, "Wooden Dining Table"),
)
_EVENTS: tuple[tuple[str, str, list[tuple[str, str, str | None]]], ...] = (
    ("evt_090", "Pip picks up a single strawberry from the bowl",
     [(PIP, "holding", BERRY), (DOOR, "sub_location", "closed"),
      (CHAIR, "sub_location", "beside wooden dining table"), (CHAIR, "orientation", "jolted")]),
    ("evt_091", ("Pip kneels and tenders the strawberry to Milo, who takes it gently from "
     "Pip's fingers and swallows it"), [(PIP, "holding", None), (BERRY, "alive_present", "consumed")]),
    ("evt_092", "Pip scratches Milo behind the ears", [(MILO, "mood", "content")]),
)  # fmt: skip
_STEPS: tuple[tuple[int, str, str], ...] = (
    (1, BERRY, "Pip picks up a single strawberry from the bowl."),
    (2, BERRY, "Pip kneels down and tenders the strawberry to Milo, who swallows it."),
    (3, MILO, "Pip Pip scratches Milo behind the ears."),
)


def _seed_scene(repo: Repo) -> None:
    steps = [
        InteractionStep(step_index=i, actor_id=PIP, target_id=t, action=a)
        for i, t, a in _STEPS
    ]
    clips = [
        ClipScript(clip_index=1, step_indices=[1], omni_prompt="Pip picks a berry."),
        ClipScript(
            clip_index=2,
            step_indices=[2, 3],
            omni_prompt="Pip feeds Milo by the wooden dining table.",
        ),
    ]
    repo.put_scene(
        Scene(id=SCENE, created_by=Role.STORY_ARCHITECT, index=9, heading="INT. KITCHEN",
              location_id="loc_cafe", time_of_day="day", interaction_steps=steps,
              clips=clips)
    )  # fmt: skip
    for n, (eid, summary, effs) in enumerate(_EVENTS):
        repo.put_event(
            Event(id=eid, created_by=Role.SCRIPT_SUPERVISOR, story_order=90 + n,
                  scene_id=SCENE, summary=summary, participants=[PIP, MILO],
                  effects=[StateEffect(entity_id=e, attribute=a, new_value=v) for e, a, v in effs])  # type: ignore[arg-type]
        )  # fmt: skip


def put_feed_shot(repo: Repo, clip_index: int, size: str) -> str:
    """(Re)place the shot rendering `clip_index` with a `size` camera; returns its id."""
    shot_id = f"shot_9_{clip_index}"
    cast = [
        CastInShot(entity_id=PIP, position="left"),
        CastInShot(entity_id=MILO, position="right"),
    ]
    repo.put_shot(
        Shot(id=shot_id, created_by=Role.DIRECTOR, scene_id=SCENE, index_in_scene=clip_index,
             story_order=89 + clip_index, duration_s=8.0, clip_index=clip_index,
             location_id="loc_cafe", cast=cast, prop_ids=[BERRY, DOOR, CHAIR, TABLE],
             camera=CameraSpec(shot_size=size, angle="eye", movement="static", lens_mm=50))  # type: ignore[arg-type]
    )  # fmt: skip
    return shot_id


def seed_feed(repo: Repo, size: str = "MCU") -> None:
    """Base graph + scene 9 with one shot per clip at camera `size`."""
    seed_valid_graph(repo)
    for eid, etype, name in _NAMES:
        repo.put_entity(
            Entity(
                id=eid,
                created_by=Role.SCRIPT_SUPERVISOR,
                entity_type=etype,
                canonical_name=name,
            )
        )
        repo.add_appearance(
            Appearance(id=f"app_{eid}_default", created_by=Role.DESIGNER,
                       status=Status.APPROVED, entity_id=eid, state_label="default",
                       visual_description=f"A distinctive {name.lower()}.")
        )  # fmt: skip
    _seed_scene(repo)
    for idx in (1, 2):
        put_feed_shot(repo, idx, size)
    rebuild_state_facts(repo)
