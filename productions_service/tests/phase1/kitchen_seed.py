"""Replay-derived fixture: production p-zyt0jprz scene 4 (feed the puppy, then slip).

Mirrors the live graph shape that broke shot 004_02: ten Events but six steps (no
step↔event links), the strawberry consumed at evt_023, positional shot story_orders
(40/41) and a director prop list that is the whole-scene closure.
"""

from __future__ import annotations

from conftest import seed_valid_graph

from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
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
BERRY, TOWEL, CHAIR, PUDDLE = "obj_berry", "obj_towel", "obj_chair", "obj_puddle"
_ENTITIES = (
    (
        PIP,
        EntityType.CHARACTER,
        "Pip",
        "A small teal robot with round orange eyes and no mouth.",
    ),
    (
        MILO,
        EntityType.CHARACTER,
        "Milo",
        "A fluffy golden retriever puppy with a pink tongue.",
    ),
    (BERRY, EntityType.OBJECT, "Single Strawberry", "One glossy red strawberry."),
    (TOWEL, EntityType.OBJECT, "Kitchen Towel", "A checkered cotton kitchen towel."),
    (
        CHAIR,
        EntityType.OBJECT,
        "Wooden Chair",
        "A honey oak chair with a slatted back.",
    ),
    (PUDDLE, EntityType.OBJECT, "Water Puddle", "A shallow puddle of spilled water."),
)
_EVENTS: tuple[tuple[str, str, list[tuple[str, str, str | None]]], ...] = (
    ("evt_020", "Pip rises, folds the damp towel and places it on the counter beside the sink",
     [(PIP, "holding", None), (TOWEL, "sub_location", "beside sink")]),
    ("evt_021", "Pip steps over to the bowl and plucks one plump strawberry", [(PIP, "holding", BERRY)]),
    ("evt_022", "Milo sits down obediently in front of Pip", [(MILO, "orientation", "sitting")]),
    ("evt_023", "Pip kneels and presents the strawberry; Milo takes it and munches it",
     [(PIP, "holding", None), (BERRY, "alive_present", "false")]),
    ("evt_024", "Pip scratches Milo behind his ears", [(PIP, "location", "loc_cafe")]),
    ("evt_025", "Pip marches back to the table and pushes the wooden chair back into place",
     [(CHAIR, "sub_location", "tucked under table")]),
    ("evt_026", "Pip dusts off his hands and strolls toward the blue door", [(PIP, "location", "loc_cafe")]),
    ("evt_027", "Pip steps onto the missed wet spot and slips", [(PIP, "orientation", "slipping")]),
    ("evt_028", "Pip lands on the floor with a clang", [(PIP, "orientation", "sitting on floor")]),
    ("evt_029", "Milo tilts his head at Pip; Pip glances at the puddle", [(MILO, "location", "loc_cafe")]),
)  # fmt: skip
_STEPS = (
    (
        1,
        TOWEL,
        "folds the damp kitchen towel and places it on the counter beside the sink",
    ),
    (
        2,
        BERRY,
        "picks up a strawberry from the bowl, kneels and offers it to Milo who munches it",
    ),
    (3, MILO, "scratches Milo behind the ears"),
    (4, CHAIR, "marches to the table and pushes the wooden chair under it"),
    (
        5,
        PUDDLE,
        "strides toward the door, steps on the wet spot and slips onto the floor",
    ),
    (6, MILO, "glances at the puddle and at Milo"),
)


def _seed_entities(repo: Repo) -> None:
    for eid, etype, name, desc in _ENTITIES:
        repo.put_entity(
            Entity(
                id=eid,
                created_by=Role.SCRIPT_SUPERVISOR,
                entity_type=etype,
                canonical_name=name,
            )
        )
        repo.add_appearance(
            Appearance(
                id=f"app_{eid}_default",
                created_by=Role.DESIGNER,
                status=Status.APPROVED,
                entity_id=eid,
                state_label="default",
                visual_description=desc,
            )
        )


def _seed_scene(repo: Repo) -> None:
    steps = [
        InteractionStep(
            step_index=i, actor_id=PIP, interaction_type="prop", target_id=t, action=a
        )
        for i, t, a in _STEPS
    ]
    clips = [
        ClipScript(
            clip_index=1,
            step_indices=[1, 2, 3],
            omni_prompt="Pip tidies up and feeds Milo.",
        ),
        ClipScript(
            clip_index=2,
            step_indices=[4, 5, 6],
            omni_prompt="Pip tucks the chair and slips.",
        ),
    ]
    repo.put_scene(
        Scene(id="scn_4", created_by=Role.STORY_ARCHITECT, index=4, heading="INT. KITCHEN",
              location_id="loc_cafe", time_of_day="day", event_ids=["evt_017", "evt_020"],
              interaction_steps=steps, clips=clips)
    )  # fmt: skip
    for n, (eid, summary, effs) in enumerate(_EVENTS):
        repo.put_event(
            Event(id=eid, created_by=Role.SCRIPT_SUPERVISOR, story_order=40 + n, scene_id="scn_4",
                  summary=summary, participants=[PIP, MILO],
                  effects=[StateEffect(entity_id=e, attribute=a, new_value=v) for e, a, v in effs])  # type: ignore[arg-type]
        )  # fmt: skip


def seed_kitchen(repo: Repo) -> None:
    """Seed the base graph plus scene 4 with two positional-order shots and closure props."""
    seed_valid_graph(repo)
    _seed_entities(repo)
    _seed_scene(repo)
    cast = [
        CastInShot(entity_id=PIP, position="left"),
        CastInShot(entity_id=MILO, position="right"),
    ]
    for idx in (1, 2):
        repo.put_shot(
            Shot(id=f"shot_4_{idx}", created_by=Role.DIRECTOR, scene_id="scn_4", index_in_scene=idx,
                 story_order=39 + idx, duration_s=8.0, clip_index=idx, location_id="loc_cafe",
                 cast=cast, prop_ids=[TOWEL, BERRY, CHAIR, PUDDLE],
                 covers_event_ids=[e for e, _, _ in _EVENTS])
        )  # fmt: skip
    rebuild_state_facts(repo)
