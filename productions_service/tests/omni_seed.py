"""Shared Omni-spec test graph: Pip (mouthless robot), Milo (puppy), towel/chair/bowl, 2 clips."""

from __future__ import annotations

from conftest import seed_valid_graph
from storygraph.clips.models import ClipScript
from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
    AttributeVal,
    CameraSpec,
    CastInShot,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    InteractionStep,
    Provenance,
    Role,
    Shot,
    StateEffect,
    Status,
)
from storygraph.state import rebuild_state_facts

_PIP_DESC = (
    "Small compact teal robot with glowing orange eyes, rendered in delicate pencil linework.. "
    "His face is a dark slate visor. His silhouette contrasts with Milo's fluffy golden fur."
)
_MILO_DESC = (
    "Milo is a golden retriever puppy animated with warm gouache. "
    "He looks nothing like Pip's teal robot chassis."
)
_CLIP1 = (
    "First, Pip unhooks the kitchen towel from the wall peg. Then Milo sniffs the puddle "
    'and wags his tail. Pip says: "Stay back, Milo!"'
)
_CLIP2 = "Pip kneels and wipes the puddle dry with the towel."


def _attr(value: str) -> dict[str, AttributeVal]:
    return {"build": AttributeVal(value=value, provenance=Provenance.FROM_TEXT)}


def _entity(eid: str, etype: EntityType, name: str, build: str = "") -> Entity:
    return Entity(
        id=eid,
        created_by=Role.SCRIPT_SUPERVISOR,
        entity_type=etype,
        canonical_name=name,
        attributes=_attr(build) if build else {},
    )


def _seed_entities(repo: Repo) -> None:
    specs = [
        (
            "char_pip",
            EntityType.CHARACTER,
            "Pip",
            "small teal robot build",
            _PIP_DESC,
            "None",
        ),
        ("char_milo", EntityType.CHARACTER, "Milo", "", _MILO_DESC, None),
        (
            "obj_towel",
            EntityType.OBJECT,
            "Kitchen Towel",
            "",
            "A mint waffle-knit towel rendered in watercolor style..",
            None,
        ),
        (
            "obj_chair",
            EntityType.OBJECT,
            "Wooden Chair",
            "",
            "A honey oak dining chair with a slatted backrest.",
            None,
        ),
        (
            "obj_bowl",
            EntityType.OBJECT,
            "Strawberry Bowl",
            "",
            "A ceramic bowl of strawberries.",
            None,
        ),
    ]
    for eid, etype, name, build, desc, wardrobe in specs:
        repo.put_entity(_entity(eid, etype, name, build))
        app = repo.add_appearance(
            Appearance(
                id=f"app_{eid}_default",
                created_by=Role.DESIGNER,
                status=Status.APPROVED,
                entity_id=eid,
                state_label="default",
                visual_description=desc,
                wardrobe=wardrobe,
            )
        )
        repo.update_appearance_status(app.id, Status.APPROVED, asset_ids=[])


def _seed_scene(repo: Repo) -> None:
    scene = repo.get_scene("scn_1")
    assert scene is not None
    steps = [
        InteractionStep(
            step_index=1,
            actor_id="char_pip",
            interaction_type="prop",
            target_id="obj_towel",
            action="unhooks the kitchen towel",
            supported_by="obj_wall_peg",
            pre_state="the towel hangs on obj_wall_peg",
            post_state="Pip holds the towel; the peg is empty",
            sound_trigger="Fabric snap as the towel leaves the peg",
        ),
        InteractionStep(
            step_index=2,
            actor_id="char_milo",
            target_id="loc_cafe",
            action="sniffs the puddle",
        ),
        InteractionStep(
            step_index=3,
            actor_id="char_pip",
            interaction_type="prop",
            target_id="obj_towel",
            action="wipes the puddle dry",
        ),
    ]
    clips = [
        ClipScript(
            clip_index=1,
            duration_s=9.0,
            omni_prompt=_CLIP1,
            step_indices=[1, 2],
            dialogue_line_ids=["dlg_pip"],
            opening_state="Pip stands by the sink; the towel hangs on obj_wall_peg.",
            closing_state="Pip holds the towel (ast_lastframe_shot_1_v2); the peg is empty..",
        ),
        ClipScript(
            clip_index=2,
            duration_s=8.0,
            omni_prompt=_CLIP2,
            step_indices=[3],
            opening_state="Pip holds the towel (ast_lastframe_shot_1_v2); the peg is empty..",
            closing_state="The floor is dry.",
        ),
    ]
    repo.put_scene(
        scene.model_copy(update={"interaction_steps": steps, "clips": clips})
    )
    repo.put_dialogue(
        DialogueLine(
            id="dlg_pip",
            created_by=Role.SCREENWRITER,
            scene_id="scn_1",
            order_in_scene=1,
            speaker_id="char_pip",
            text="Stay back, Milo!",
        )
    )
    repo.put_event(
        Event(
            id="evt_chair",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=5,
            scene_id="scn_1",
            summary="chair placed",
            participants=["obj_chair"],
            effects=[
                StateEffect(
                    entity_id="obj_chair",
                    attribute="supported_by",
                    new_value="beside the dining table",
                )
            ],
        )
    )
    rebuild_state_facts(repo)


def _seed_shots(repo: Repo) -> None:
    base = seed_valid_graph(repo)
    _seed_entities(repo)
    _seed_scene(repo)
    sounds = {
        "sfx": [
            "Towel hook snap",
            "Towel hook snap",
            "Distant traffic",
            "Clock ticking",
            "Fridge hum",
        ],
        "foley_sfx": [
            "Fabric snap as the towel leaves the peg",
            "Puppy sniffing the puddle",
        ],
        "environmental_sfx": ["Rain on the window"],
    }
    cast = [
        CastInShot(entity_id="char_pip", position="center", speaking=True),
        CastInShot(entity_id="char_milo", position="right"),
    ]
    repo.put_shot(
        base.model_copy(
            update={
                "duration_s": 9.0,
                "cast": cast,
                "prop_ids": ["obj_towel", "obj_chair"],
                "dialogue_ids": ["dlg_pip"],
                "camera": CameraSpec(movement="track", focus_target_id="char_pip"),
                "beats": [],
                "music_cue_id": None,
                **sounds,
            }
        )
    )
    repo.put_shot(
        Shot(
            id="shot_2",
            created_by=Role.DIRECTOR,
            scene_id="scn_1",
            index_in_scene=2,
            story_order=16,
            duration_s=8.0,
            clip_index=2,
            location_id="loc_cafe",
            cast=cast[:1],
            prop_ids=["obj_towel"],
            continue_from_last_frame=True,
        )
    )
