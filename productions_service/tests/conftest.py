"""Shared pytest fixtures and valid StoryGraph seeding helpers for productions_service tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.schema import (
    ActionBeat,
    Appearance,
    Asset,
    CastInShot,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    Role,
    Scene,
    Shot,
    StateEffect,
    Status,
    StyleGuide,
)
from storygraph.state import rebuild_state_facts
from storygraph.store import LocalBlobStore, MemoryStore


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Repo:
    store = MemoryStore(project_id="test_proj")
    blobs = LocalBlobStore(root_dir=tmp_path / "blobs", project_id="test_proj")
    return Repo(store=store, blobs=blobs)


@pytest.fixture()
def default_cfg(tmp_path: Path) -> Config:
    cfg = Config.load()
    cfg.blobs.local_root = str(tmp_path / "blobs")
    return cfg


def _seed_style_and_entities(repo: Repo) -> None:
    """Seed StyleGuide, Character, Location, Object, and Scene nodes."""
    repo.put_style_guide(
        StyleGuide(
            id="style_guide",
            created_by=Role.STORY_ARCHITECT,
            visual_medium="35mm film",
            palette=["teal", "amber"],
            lens_language="35mm",
            lighting_rules="naturalistic",
        )
    )
    for eid, etype, name, aliases in [
        ("char_arjun", EntityType.CHARACTER, "Arjun", ["Detective Arjun"]),
        ("loc_cafe", EntityType.LOCATION, "Cafe", []),
        ("obj_compass", EntityType.OBJECT, "Brass Compass", []),
    ]:
        repo.put_entity(
            Entity(
                id=eid,
                created_by=Role.SCRIPT_SUPERVISOR,
                entity_type=etype,
                canonical_name=name,
                aliases=aliases,
            )
        )
    repo.put_scene(
        Scene(
            id="scn_1",
            created_by=Role.STORY_ARCHITECT,
            index=1,
            heading="INT. CAFE - NIGHT",
            location_id="loc_cafe",
            time_of_day="night",
        )
    )


def _seed_events_and_state(repo: Repo) -> None:
    """Seed causal Events and rebuild derived StateFacts."""
    eff_1 = [
        StateEffect(entity_id="char_arjun", attribute="location", new_value="loc_cafe"),
        StateEffect(
            entity_id="char_arjun", attribute="wearing", new_value="trenchcoat"
        ),
        StateEffect(
            entity_id="char_arjun", attribute="holding", new_value="obj_compass"
        ),
        StateEffect(
            entity_id="obj_compass", attribute="location", new_value="loc_cafe"
        ),
    ]
    repo.put_event(
        Event(
            id="evt_1",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=10,
            scene_id="scn_1",
            summary="Arjun enters wearing trenchcoat holding compass",
            participants=["char_arjun"],
            effects=eff_1,
        )
    )
    eff_2 = [
        StateEffect(
            entity_id="char_arjun", attribute="wearing", new_value="formal_suit"
        )
    ]
    repo.put_event(
        Event(
            id="evt_2",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=20,
            scene_id="scn_1",
            summary="Arjun changes into formal_suit",
            participants=["char_arjun"],
            effects=eff_2,
        )
    )
    rebuild_state_facts(repo)


def _seed_appearances_and_assets(repo: Repo) -> None:
    """Create approved Appearances and Assets for character states, location, and prop."""
    specs = [
        ("char_arjun", "character_sheet", "trenchcoat"),
        ("char_arjun", "character_sheet", "formal_suit"),
        ("loc_cafe", "location_plate", "default"),
        ("obj_compass", "prop_sheet", "default"),
    ]
    for eid, kind, lbl in specs:
        app_node = repo.add_appearance(
            Appearance(
                id=f"app_{eid}_{lbl}",
                created_by=Role.DESIGNER,
                status=Status.APPROVED,
                entity_id=eid,
                state_label=lbl,
                visual_description=f"{eid} {lbl} description",
                wardrobe=lbl if eid == "char_arjun" else None,
            )
        )
        uri = repo.blobs.put_bytes(f"assets/{app_node.id}.png", b"png", "image/png")
        asset = repo.add_asset(
            Asset(
                id=f"ast_{eid}_{lbl}",
                created_by=Role.DESIGNER,
                status=Status.APPROVED,
                kind=kind,
                uri=uri,
                sha256="sha_" + app_node.id,
                depicts_entity_ids=[eid],
                appearance_ids=[app_node.id],
                generation_prompt="prompt",
                model="mock",
            )  # type: ignore[arg-type]
        )
        repo.update_appearance_status(
            app_node.id, Status.APPROVED, asset_ids=[asset.id]
        )


def seed_valid_graph(repo: Repo) -> Shot:
    """Populate `repo` with a complete, valid StoryGraph and return the seeded `shot_1`."""
    _seed_style_and_entities(repo)
    _seed_events_and_state(repo)
    _seed_appearances_and_assets(repo)
    repo.put_dialogue(
        DialogueLine(
            id="dlg_1",
            created_by=Role.SCREENWRITER,
            scene_id="scn_1",
            order_in_scene=1,
            speaker_id="char_arjun",
            text="The compass points north.",
        )
    )
    beat = ActionBeat(
        t_start_s=0.0,
        t_end_s=5.0,
        description="Arjun checks the compass.",
        subject_ids=["char_arjun", "obj_compass"],
    )
    return repo.put_shot(
        Shot(
            id="shot_1",
            created_by=Role.DIRECTOR,
            scene_id="scn_1",
            index_in_scene=1,
            story_order=15,
            covers_event_ids=["evt_1", "evt_2"],
            duration_s=5.0,
            location_id="loc_cafe",
            cast=[CastInShot(entity_id="char_arjun", speaking=True)],
            prop_ids=["obj_compass"],
            beats=[beat],
            dialogue_ids=["dlg_1"],
        )
    )
