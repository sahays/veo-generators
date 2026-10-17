"""Milestones 1 & 2: Store Contract, Blob Store, Schema Round-Trip, Versioning & Staleness tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from storygraph.errors import AlreadyExists, DocTooLarge
from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
    Asset,
    AttributeVal,
    CastInShot,
    ChangeRequest,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    Gate,
    GenerationRun,
    MusicCue,
    Provenance,
    Role,
    Scene,
    Shot,
    StageRun,
    StateEffect,
    StateFact,
    Status,
    StyleGuide,
)
from storygraph.store import LocalBlobStore, MemoryStore, decode, encode


def test_store_crud_and_queries() -> None:
    store = MemoryStore(project_id="p1")
    assert store.get("entities", "char_1") is None
    store.set(
        "entities",
        "char_1",
        {
            "id": "char_1",
            "entity_type": "character",
            "order": 2,
            "tags": ["hero", "lead"],
        },
    )
    store.set(
        "entities",
        "char_2",
        {"id": "char_2", "entity_type": "character", "order": 1, "tags": ["ally"]},
    )
    store.set(
        "entities",
        "loc_1",
        {"id": "loc_1", "entity_type": "location", "order": 3, "tags": ["interior"]},
    )
    chars = store.query(
        "entities", filters=[("entity_type", "==", "character")], order_by="order"
    )
    assert [c["id"] for c in chars] == ["char_2", "char_1"]
    desc_chars = store.query(
        "entities",
        filters=[("entity_type", "==", "character")],
        order_by="-order",
        limit=1,
    )
    assert [c["id"] for c in desc_chars] == ["char_1"]
    tagged = store.query("entities", filters=[("tags", "array_contains", "hero")])
    assert [t["id"] for t in tagged] == ["char_1"]
    in_res = store.query("entities", filters=[("id", "in", ["char_2", "loc_1"])])
    assert {r["id"] for r in in_res} == {"char_2", "loc_1"}
    with pytest.raises(ValueError, match="at most 30"):
        store.query("entities", filters=[("id", "in", [f"id_{i}" for i in range(31)])])


def test_store_batches_transactions_and_blobs(tmp_path: Path) -> None:
    store = MemoryStore(project_id="p1")
    store.set("entities", "char_1", {"id": "char_1", "order": 2})
    store.set("entities", "char_2", {"id": "char_2", "order": 1})
    with store.batch() as b:
        b.set("entities", "obj_1", {"id": "obj_1", "entity_type": "object", "order": 4})
        b.delete("entities", "char_2")
    assert store.get("entities", "obj_1") == {
        "id": "obj_1",
        "entity_type": "object",
        "order": 4,
    }
    assert store.get("entities", "char_2") is None
    with store.transaction() as tx:
        cur = tx.get("entities", "char_1")
        assert cur is not None
        tx.set("entities", "char_1", {**cur, "order": 99})
        assert tx.get("entities", "char_1")["order"] == 99  # type: ignore[index]
    assert store.get("entities", "char_1")["order"] == 99  # type: ignore[index]
    with pytest.raises(DocTooLarge):
        store.set("entities", "huge", {"blob": "x" * 950_000})
    blobs = LocalBlobStore(tmp_path / "blobs", project_id="p1")
    uri = blobs.put_bytes("assets/test.png", b"\x89PNG_PAYLOAD", "image/png")
    assert uri.startswith("file://") and blobs.exists(uri)
    assert blobs.get_bytes(uri) == b"\x89PNG_PAYLOAD"


def _sample_nodes_world() -> list[Any]:
    attr = {"age": AttributeVal(value="32", provenance=Provenance.FROM_TEXT)}
    eff = [
        StateEffect(entity_id="char_arjun", attribute="location", new_value="loc_cafe")
    ]
    return [
        Entity(
            id="char_arjun",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.CHARACTER,
            canonical_name="Arjun",
            aliases=["Detective Arjun"],
            attributes=attr,
        ),
        Event(
            id="evt_1",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=10,
            scene_id="scn_1",
            summary="Arjun enters the cafe",
            participants=["char_arjun"],
            effects=eff,
        ),
        StateFact(
            id="sf_0001",
            created_by=Role.PIPELINE,
            entity_id="char_arjun",
            attribute="location",
            value="loc_cafe",
            valid_from_order=10,
            valid_to_order=20,
            caused_by_event_id="evt_1",
        ),
        Appearance(
            id="app_char_arjun_default_v1",
            created_by=Role.CHARACTER_DESIGNER,
            entity_id="char_arjun",
            state_label="default",
            visual_description="Tall detective with sharp eyes",
            wardrobe="Trenchcoat",
        ),
        Asset(
            id="ast_char_arjun_default_v1",
            created_by=Role.CHARACTER_DESIGNER,
            kind="character_sheet",
            uri="file:///tmp/a.png",
            sha256="abc123",
            depicts_entity_ids=["char_arjun"],
            appearance_ids=["app_char_arjun_default_v1"],
            generation_prompt="Character sheet",
            model="gemini-nano-banana-2.1",
        ),
        StyleGuide(
            id="style_guide",
            created_by=Role.STORY_ARCHITECT,
            visual_medium="35mm anamorphic",
            palette=["teal", "amber"],
            lens_language="Panavision primes",
            lighting_rules="Chiaroscuro",
        ),
        Scene(
            id="scn_1",
            created_by=Role.STORY_ARCHITECT,
            index=1,
            heading="INT. CAFE - NIGHT",
            location_id="loc_cafe",
            time_of_day="night",
        ),
    ]


def _sample_nodes_execution() -> list[Any]:
    return [
        DialogueLine(
            id="dlg_1",
            created_by=Role.SCREENWRITER,
            scene_id="scn_1",
            order_in_scene=1,
            speaker_id="char_arjun",
            text="We meet again.",
        ),
        MusicCue(
            id="cue_1",
            created_by=Role.MUSIC_DIRECTOR,
            scene_id="scn_1",
            mood="tense",
            instrumentation="cello",
            tempo_bpm=90,
        ),
        Shot(
            id="shot_1",
            created_by=Role.DIRECTOR,
            scene_id="scn_1",
            index_in_scene=1,
            story_order=10,
            duration_s=5.0,
            location_id="loc_cafe",
        ),
        GenerationRun(
            id="run_1",
            created_by=Role.PIPELINE,
            shot_id="shot_1",
            attempt=1,
            provider="mock",
            model="veo",
            compiled_prompt="PROMPT",
            seed=42,
            package_hash="hash123",
        ),
        ChangeRequest(
            id="cr_1",
            created_by=Role.CRITIC,
            from_role=Role.CRITIC,
            to_role=Role.DIRECTOR,
            target_node_id="shot_1",
            reason="Resplit shot",
        ),
        Gate(id="G1", created_by=Role.PIPELINE, gate_id="G1", stage="S1_EXTRACT"),
        StageRun(
            id="sr_1", created_by=Role.PIPELINE, stage="S1_EXTRACT", input_hash="h1"
        ),
    ]


def test_all_14_node_types_round_trip() -> None:
    nodes = _sample_nodes_world() + _sample_nodes_execution()
    assert len(nodes) == 14
    for node in nodes:
        assert decode(encode(node)) == node


def _seed_v1_appearances(tmp_repo: Repo) -> tuple[Appearance, Appearance]:
    tmp_repo.put_entity(
        Entity(
            id="char_arjun",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.CHARACTER,
            canonical_name="Arjun",
        )
    )
    tmp_repo.put_entity(
        Entity(
            id="loc_cafe",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.LOCATION,
            canonical_name="Corner Cafe",
        )
    )
    app_v1 = tmp_repo.add_appearance(
        Appearance(
            id="app_char_arjun_default",
            created_by=Role.CHARACTER_DESIGNER,
            status=Status.APPROVED,
            entity_id="char_arjun",
            state_label="default",
            visual_description="Arjun v1 look",
        )
    )
    loc_app = tmp_repo.add_appearance(
        Appearance(
            id="app_loc_cafe_default",
            created_by=Role.LOCATION_DESIGNER,
            status=Status.APPROVED,
            entity_id="loc_cafe",
            state_label="default",
            visual_description="Cafe v1 look",
        )
    )
    return app_v1, loc_app


def test_repo_versioning_append_only_and_staleness_propagation(tmp_repo: Repo) -> None:
    app_v1, loc_app = _seed_v1_appearances(tmp_repo)
    assert app_v1.id == "app_char_arjun_default_v1" and app_v1.version == 1
    shot = tmp_repo.put_shot(
        Shot(
            id="shot_01",
            created_by=Role.DIRECTOR,
            scene_id="scn_1",
            index_in_scene=1,
            story_order=10,
            duration_s=5.0,
            location_id="loc_cafe",
            cast=[CastInShot(entity_id="char_arjun")],
        )
    )
    assert app_v1.id in shot.ref_ids and loc_app.id in shot.ref_ids and not shot.stale
    app_v2 = tmp_repo.add_appearance(
        Appearance(
            id="app_char_arjun_default",
            created_by=Role.CHARACTER_DESIGNER,
            status=Status.APPROVED,
            entity_id="char_arjun",
            state_label="default",
            visual_description="Arjun v2 updated look",
        )
    )
    assert app_v2.id == "app_char_arjun_default_v2" and app_v2.supersedes == app_v1.id
    reloaded_v1 = tmp_repo.get_appearance(app_v1.id)
    assert reloaded_v1 is not None and reloaded_v1.status == Status.SUPERSEDED
    reloaded_shot = tmp_repo.get_shot("shot_01")
    assert reloaded_shot is not None and reloaded_shot.stale is True

    run = GenerationRun(
        id="run_unique_1",
        created_by=Role.PIPELINE,
        shot_id="shot_01",
        attempt=1,
        provider="mock",
        model="veo",
        compiled_prompt="test",
        seed=1,
        package_hash="h",
    )
    tmp_repo.add_generation_run(run)
    with pytest.raises(AlreadyExists):
        tmp_repo.add_generation_run(run)
