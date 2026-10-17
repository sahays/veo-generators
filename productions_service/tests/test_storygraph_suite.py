"""Comprehensive unit & contract test suite for the Story-to-Video Graph Production Service.

Covers all contract milestones:
1. Store Contract (`MemoryStore` + `LocalBlobStore`, filters, order_by, batch, transaction, `DocTooLarge` guard)
2. Schema & Codec round-trip across all 14 node types, `Repo` versioning (`v1` -> `v2`), append-only immutability, and `ref_ids` staleness propagation
3. State Engine (`rebuild_state_facts`, `state_at`, `appearance_for`) and Validator rules `V1`–`V13`
4. Permission Matrix across all 10 roles (`STORY_ARCHITECT`, `SCRIPT_SUPERVISOR`, `SCREENWRITER`, `CHARACTER_DESIGNER`, `LOCATION_DESIGNER`, `OBJECT_DESIGNER`, `DESIGNER`, `DIRECTOR`, `MUSIC_DIRECTOR`, `CRITIC`) + entity-type isolation + audit log entries
5. Reference Budgeter (`select_references`, Pillow composite sheets, verbal injection) and Jinja2 Prompt Compiler (`compile_shot`, hash stability, length trimming, `PromptTooLong`)
6. End-to-End Pipeline (`S0_INGEST` .. `S10_ASSEMBLE`), Gate blocking (`G1`, `G2`, `G3`), retry & `ChangeRequest` loop, idempotency, budget caps, and FastAPI microservice endpoints
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from main import app
from storygraph.adapters.mock import (
    MockImageGenerator,
    MockLLMClient,
    MockVideoGenerator,
    MockVLMProvider,
)
from storygraph.agents.runner import run_role
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.errors import (
    AlreadyExists,
    BudgetExceeded,
    DocTooLarge,
    GateBlocked,
    PermissionDenied,
    PromptTooLong,
    StructuredOutputError,
)
from storygraph.pipeline import Pipeline, Stage, approve_gate
from storygraph.repo import Repo
from storygraph.schema import (
    ActionBeat,
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
from storygraph.state import appearance_for, rebuild_state_facts, state_at
from storygraph.store import LocalBlobStore, MemoryStore, decode, encode
from storygraph.tools import write_tools as wt
from storygraph.tools.registry import ROLE_SCOPE, ToolContext
from storygraph.validate import validate_all, validate_shot
from storygraph.views import shot_view


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


# ─────────────────────────────────────────────────────────────────────────────
# Milestone 1: Store Contract & Blob Store
# ─────────────────────────────────────────────────────────────────────────────


def test_store_crud_queries_batches_and_size_guard(tmp_path: Path) -> None:
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

    assert store.get("entities", "char_1")["order"] == 2
    chars = store.query(
        "entities",
        filters=[("entity_type", "==", "character")],
        order_by="order",
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

    # Batch atomic write
    with store.batch() as b:
        b.set("entities", "obj_1", {"id": "obj_1", "entity_type": "object", "order": 4})
        b.delete("entities", "char_2")
    assert store.get("entities", "obj_1") is not None
    assert store.get("entities", "char_2") is None

    # Transaction read-your-own-writes
    with store.transaction() as tx:
        cur = tx.get("entities", "char_1")
        assert cur is not None
        tx.set("entities", "char_1", {**cur, "order": 99})
        assert tx.get("entities", "char_1")["order"] == 99
    assert store.get("entities", "char_1")["order"] == 99

    # DocTooLarge guard
    with pytest.raises(DocTooLarge):
        store.set("entities", "huge", {"blob": "x" * 950_000})

    # LocalBlobStore round-trip
    blobs = LocalBlobStore(tmp_path / "blobs", project_id="p1")
    uri = blobs.put_bytes("assets/test.png", b"\x89PNG_PAYLOAD", "image/png")
    assert uri.startswith("file://")
    assert blobs.exists(uri)
    assert blobs.get_bytes(uri) == b"\x89PNG_PAYLOAD"


# ─────────────────────────────────────────────────────────────────────────────
# Milestone 2: Schema Round-Trip, Versioning, Immutability & Staleness Propagation
# ─────────────────────────────────────────────────────────────────────────────


def test_all_14_node_types_round_trip() -> None:
    nodes = [
        Entity(
            id="char_arjun",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.CHARACTER,
            canonical_name="Arjun",
            aliases=["Detective Arjun"],
            attributes={
                "age": AttributeVal(value="32", provenance=Provenance.FROM_TEXT)
            },
        ),
        Event(
            id="evt_1",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=10,
            scene_id="scn_1",
            summary="Arjun enters the cafe",
            participants=["char_arjun"],
            effects=[
                StateEffect(
                    entity_id="char_arjun", attribute="location", new_value="loc_cafe"
                )
            ],
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
        Gate(
            id="G1",
            created_by=Role.PIPELINE,
            gate_id="G1",
            stage="S1_EXTRACT",
        ),
        StageRun(
            id="sr_1",
            created_by=Role.PIPELINE,
            stage="S1_EXTRACT",
            input_hash="h1",
        ),
    ]
    assert len(nodes) == 14
    for node in nodes:
        encoded = encode(node)
        decoded = decode(encoded)
        assert decoded == node


def test_repo_versioning_append_only_and_staleness_propagation(tmp_repo: Repo) -> None:
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
    assert app_v1.id == "app_char_arjun_default_v1"
    assert app_v1.version == 1

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
    assert app_v1.id in shot.ref_ids
    assert loc_app.id in shot.ref_ids
    assert shot.stale is False

    # Adding a v2 appearance supersedes v1 and marks shot_01 stale!
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
    assert app_v2.id == "app_char_arjun_default_v2"
    assert app_v2.version == 2
    assert app_v2.supersedes == app_v1.id
    reloaded_v1 = tmp_repo.get_appearance(app_v1.id)
    assert reloaded_v1 is not None and reloaded_v1.status == Status.SUPERSEDED

    reloaded_shot = tmp_repo.get_shot("shot_01")
    assert reloaded_shot is not None
    assert reloaded_shot.stale is True
    assert "superseded" in (reloaded_shot.stale_reason or "")

    # Append-only nodes raise AlreadyExists on duplicate ID
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


# ─────────────────────────────────────────────────────────────────────────────
# Milestone 3: State Engine & Validator Rules V1–V13
# ─────────────────────────────────────────────────────────────────────────────


def _seed_valid_graph(repo: Repo) -> Shot:
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
    repo.put_entity(
        Entity(
            id="char_arjun",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.CHARACTER,
            canonical_name="Arjun",
            aliases=["Detective Arjun"],
        )
    )
    repo.put_entity(
        Entity(
            id="loc_cafe",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.LOCATION,
            canonical_name="Cafe",
        )
    )
    repo.put_entity(
        Entity(
            id="obj_compass",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.OBJECT,
            canonical_name="Brass Compass",
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
    repo.put_event(
        Event(
            id="evt_1",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=10,
            scene_id="scn_1",
            summary="Arjun enters wearing trenchcoat holding compass",
            participants=["char_arjun"],
            effects=[
                StateEffect(
                    entity_id="char_arjun", attribute="location", new_value="loc_cafe"
                ),
                StateEffect(
                    entity_id="char_arjun",
                    attribute="wearing",
                    new_value="trenchcoat",
                ),
                StateEffect(
                    entity_id="char_arjun",
                    attribute="holding",
                    new_value="obj_compass",
                ),
                StateEffect(
                    entity_id="obj_compass", attribute="location", new_value="loc_cafe"
                ),
            ],
        )
    )
    repo.put_event(
        Event(
            id="evt_2",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=20,
            scene_id="scn_1",
            summary="Arjun changes into formal_suit",
            participants=["char_arjun"],
            effects=[
                StateEffect(
                    entity_id="char_arjun",
                    attribute="wearing",
                    new_value="formal_suit",
                ),
            ],
        )
    )
    rebuild_state_facts(repo)

    # Create approved appearances & assets for character (both states), location, and prop
    for eid, kind, lbl in [
        ("char_arjun", "character_sheet", "trenchcoat"),
        ("char_arjun", "character_sheet", "formal_suit"),
        ("loc_cafe", "location_plate", "default"),
        ("obj_compass", "prop_sheet", "default"),
    ]:
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
                kind=kind,  # type: ignore[arg-type]
                uri=uri,
                sha256="sha_" + app_node.id,
                depicts_entity_ids=[eid],
                appearance_ids=[app_node.id],
                generation_prompt="prompt",
                model="mock",
            )
        )
        repo.update_appearance_status(
            app_node.id, Status.APPROVED, asset_ids=[asset.id]
        )

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
    shot = repo.put_shot(
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
            beats=[
                ActionBeat(
                    t_start_s=0.0,
                    t_end_s=5.0,
                    description="Arjun checks the compass.",
                    subject_ids=["char_arjun", "obj_compass"],
                )
            ],
            dialogue_ids=["dlg_1"],
        )
    )
    return shot


def test_state_engine_and_validator_v1_through_v13(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = _seed_valid_graph(tmp_repo)

    # Verify half-open intervals [10, 20) and [20, None)
    assert state_at(tmp_repo, "char_arjun", 15)["wearing"] == "trenchcoat"
    assert state_at(tmp_repo, "char_arjun", 20)["wearing"] == "formal_suit"
    assert appearance_for(tmp_repo, "char_arjun", 15).state_label == "trenchcoat"
    assert appearance_for(tmp_repo, "char_arjun", 25).state_label == "formal_suit"

    # Valid graph has 0 issues
    assert validate_all(tmp_repo, default_cfg) == []

    # V1 failure: unapproved appearance
    bad_v1 = shot.model_copy(update={"location_appearance_id": ""})
    assert any(i.code == "V1" for i in validate_shot(tmp_repo, bad_v1, default_cfg))

    # V2 failure: wrong wardrobe appearance at order 15
    bad_v2 = shot.model_copy(
        update={
            "cast": [
                CastInShot(
                    entity_id="char_arjun",
                    appearance_id="app_char_arjun_formal_suit_v1",
                )
            ]
        }
    )
    assert any(i.code == "V2" for i in validate_shot(tmp_repo, bad_v2, default_cfg))

    # V3 failure: cast location mismatch
    bad_v3 = shot.model_copy(update={"location_id": "loc_other"})
    assert any(i.code == "V3" for i in validate_shot(tmp_repo, bad_v3, default_cfg))

    # V4 failure: prop at another location and not held
    tmp_repo.put_event(
        Event(
            id="evt_prop_move",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=12,
            scene_id="scn_1",
            summary="Arjun sets down compass in vault",
            participants=["char_arjun"],
            effects=[
                StateEffect(
                    entity_id="char_arjun", attribute="holding", new_value=None
                ),
                StateEffect(
                    entity_id="obj_compass",
                    attribute="location",
                    new_value="loc_vault",
                ),
            ],
        )
    )
    rebuild_state_facts(tmp_repo)
    assert any(i.code == "V4" for i in validate_shot(tmp_repo, shot, default_cfg))

    # V5 failure: alive_present == "false"
    tmp_repo.put_event(
        Event(
            id="evt_absent",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=14,
            scene_id="scn_1",
            summary="Arjun exits",
            participants=["char_arjun"],
            effects=[
                StateEffect(
                    entity_id="char_arjun",
                    attribute="alive_present",
                    new_value="false",
                )
            ],
        )
    )
    rebuild_state_facts(tmp_repo)
    assert any(i.code == "V5" for i in validate_shot(tmp_repo, shot, default_cfg))

    # V6 failure: duration > max_duration_s
    bad_v6 = shot.model_copy(update={"duration_s": 12.0})
    assert any(i.code == "V6" for i in validate_shot(tmp_repo, bad_v6, default_cfg))

    # V7 failure: overlapping beats
    bad_v7 = shot.model_copy(
        update={
            "beats": [
                ActionBeat(t_start_s=0.0, t_end_s=3.0, description="Beat 1"),
                ActionBeat(
                    t_start_s=2.0, t_end_s=5.0, description="Overlapping Beat 2"
                ),
            ]
        }
    )
    assert any(i.code == "V7" for i in validate_shot(tmp_repo, bad_v7, default_cfg))

    # V8 failure: speech word-rate > 2.8 words/sec
    tmp_repo.put_dialogue(
        DialogueLine(
            id="dlg_long",
            created_by=Role.SCREENWRITER,
            scene_id="scn_1",
            order_in_scene=2,
            speaker_id="char_arjun",
            text=" ".join(["word"] * 25),
        )
    )
    bad_v8 = shot.model_copy(update={"duration_s": 2.0, "dialogue_ids": ["dlg_long"]})
    assert any(i.code == "V8" for i in validate_shot(tmp_repo, bad_v8, default_cfg))

    # V9 failure: dialogue speaker not in cast
    bad_v9 = shot.model_copy(update={"cast": []})
    assert any(i.code == "V9" for i in validate_shot(tmp_repo, bad_v9, default_cfg))

    # V11 warning: continue_from_last_frame without matching prev_shot location
    bad_v11 = shot.model_copy(update={"continue_from_last_frame": True})
    assert any(
        i.code == "V11" and i.severity == "warn"
        for i in validate_shot(tmp_repo, bad_v11, default_cfg, prev_shot=None)
    )

    # V13 failure: stale shot
    bad_v13 = shot.model_copy(update={"stale": True, "stale_reason": "test stale"})
    assert any(i.code == "V13" for i in validate_shot(tmp_repo, bad_v13, default_cfg))

    # V10 warning & V12 error in validate_all
    tmp_repo.put_entity(
        Entity(
            id="char_dup",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.CHARACTER,
            canonical_name="Arjun",  # duplicates char_arjun
        )
    )
    all_issues = validate_all(tmp_repo, default_cfg)
    assert any(i.code == "V12" for i in all_issues)
    assert any(
        i.code == "V10" for i in all_issues
    )  # evt_prop_move & evt_absent uncovered


# ─────────────────────────────────────────────────────────────────────────────
# Milestone 4: Role Permission Matrix, Entity-Type Isolation & Repair Loop
# ─────────────────────────────────────────────────────────────────────────────


def test_role_permission_matrix_and_entity_type_isolation(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    _seed_valid_graph(tmp_repo)

    # 1. STORY_ARCHITECT can write StyleGuide/Scene/Event, but NOT Shot or Appearance
    sa_ctx = ToolContext(repo=tmp_repo, role=Role.STORY_ARCHITECT, cfg=default_cfg)
    wt.put_style_guide(
        sa_ctx,
        visual_medium="Cinema",
        palette=["gold"],
        lens_language="50mm",
        lighting_rules="soft",
    )
    with pytest.raises(PermissionDenied):
        wt.put_shot(
            sa_ctx,
            shot_id="s_illegal",
            scene_id="scn_1",
            index_in_scene=2,
            story_order=20,
            duration_s=4.0,
            location_id="loc_cafe",
        )

    # 2. CHARACTER_DESIGNER can modify character Entity/Appearance/Asset, but NOT location or object!
    cd_ctx = ToolContext(repo=tmp_repo, role=Role.CHARACTER_DESIGNER, cfg=default_cfg)
    wt.set_character_attributes(
        cd_ctx, "char_arjun", {"hair": "black wavy"}, provenance="invented"
    )
    with pytest.raises(PermissionDenied):
        wt.set_location_attributes(
            cd_ctx, "loc_cafe", {"lighting": "neon"}, provenance="invented"
        )
    with pytest.raises(PermissionDenied):
        wt.add_appearance(
            cd_ctx,
            entity_id="loc_cafe",
            state_label="night",
            visual_description="Illegal location appearance from character designer",
        )

    # 3. LOCATION_DESIGNER can modify location, but NOT character or object
    ld_ctx = ToolContext(repo=tmp_repo, role=Role.LOCATION_DESIGNER, cfg=default_cfg)
    wt.set_location_attributes(
        ld_ctx, "loc_cafe", {"lighting": "warm tungsten"}, provenance="invented"
    )
    with pytest.raises(PermissionDenied):
        wt.set_character_attributes(
            ld_ctx, "char_arjun", {"build": "tall"}, provenance="invented"
        )

    # 4. OBJECT_DESIGNER can modify object, but NOT character or location
    od_ctx = ToolContext(repo=tmp_repo, role=Role.OBJECT_DESIGNER, cfg=default_cfg)
    wt.set_object_attributes(
        od_ctx, "obj_compass", {"material": "aged brass"}, provenance="invented"
    )
    with pytest.raises(PermissionDenied):
        wt.set_location_attributes(
            od_ctx, "loc_cafe", {"floor": "wood"}, provenance="invented"
        )

    # 5. Designers cannot overwrite FROM_TEXT attributes
    ss_ctx = ToolContext(repo=tmp_repo, role=Role.SCRIPT_SUPERVISOR, cfg=default_cfg)
    wt.put_entity(
        ss_ctx,
        entity_id="char_arjun",
        entity_type="character",
        canonical_name="Arjun",
        attributes={
            "eyes": AttributeVal(value="hazel", provenance=Provenance.FROM_TEXT)
        },
    )
    with pytest.raises(PermissionDenied, match="FROM_TEXT"):
        wt.set_character_attributes(
            cd_ctx, "char_arjun", {"eyes": "blue"}, provenance="invented"
        )

    # 6. SCREENWRITER can write DialogueLine and Scene script, but NOT Entity or Shot
    sw_ctx = ToolContext(repo=tmp_repo, role=Role.SCREENWRITER, cfg=default_cfg)
    wt.update_scene_script(sw_ctx, "scn_1", summary="Updated summary", mood="noir")
    with pytest.raises(PermissionDenied):
        wt.put_entity(
            sw_ctx,
            entity_id="char_new",
            entity_type="character",
            canonical_name="New",
        )

    # 7. DIRECTOR can write Shot and ChangeRequest, but NOT DialogueLine or Appearance
    dir_ctx = ToolContext(repo=tmp_repo, role=Role.DIRECTOR, cfg=default_cfg)
    with pytest.raises(PermissionDenied):
        wt.put_dialogue(
            dir_ctx,
            line_id="dlg_illegal",
            scene_id="scn_1",
            order_in_scene=2,
            speaker_id="char_arjun",
            text="Director cannot write dialogue",
        )

    # 8. MUSIC_DIRECTOR can write MusicCue and Shot audio, but NOT Shot camera
    md_ctx = ToolContext(repo=tmp_repo, role=Role.MUSIC_DIRECTOR, cfg=default_cfg)
    wt.put_music_cue(
        md_ctx,
        cue_id="cue_test",
        scene_id="scn_1",
        mood="brooding",
        instrumentation="piano",
        tempo_bpm=76,
    )
    wt.set_shot_audio(md_ctx, "shot_1", "cue_test", ["rain", "footsteps"])
    with pytest.raises(PermissionDenied):
        wt.put_shot(
            md_ctx,
            shot_id="shot_1",
            scene_id="scn_1",
            index_in_scene=1,
            story_order=15,
            duration_s=5.0,
            location_id="loc_cafe",
        )

    # 9. CRITIC can write QA scores / asset critique / ChangeRequest, but NOT Shot or Entity
    cr_ctx = ToolContext(repo=tmp_repo, role=Role.CRITIC, cfg=default_cfg)
    wt.create_change_request(
        cr_ctx, to_role=Role.DIRECTOR, target_node_id="shot_1", reason="Fix framing"
    )
    with pytest.raises(PermissionDenied):
        wt.put_scene(
            cr_ctx,
            scene_id="scn_1",
            index=1,
            heading="INT",
            location_id="loc_cafe",
            time_of_day="night",
        )

    # Verify audit log captured all successful mutations
    audits = tmp_repo.list_audit_entries()
    assert len(audits) >= 6
    assert len(ROLE_SCOPE) >= 10


def test_structured_output_repair_loop(tmp_repo: Repo, default_cfg: Config) -> None:
    from storygraph.agents.roles import ScreenwriterOutput

    sw_ctx = ToolContext(repo=tmp_repo, role=Role.SCREENWRITER, cfg=default_cfg)

    # 1st response is invalid JSON, 2nd response is valid JSON -> succeeds on repair retry
    mock_ok = MockLLMClient(
        scripted_responses={
            str(Role.SCREENWRITER): [
                "NOT VALID JSON {{{",
                '{"summary": "Repaired scene", "mood": "tense", "dialogue_lines": []}',
            ]
        }
    )
    res = run_role(
        role=Role.SCREENWRITER,
        ctx=sw_ctx,
        user_prompt="Write scene",
        output_schema=ScreenwriterOutput,
        mock_llm=mock_ok,
    )
    assert res.output.summary == "Repaired scene"

    # 3 consecutive invalid JSON responses -> raises StructuredOutputError
    mock_bad = MockLLMClient(
        scripted_responses={str(Role.SCREENWRITER): ["bad1", "bad2", "bad3"]}
    )
    with pytest.raises(StructuredOutputError):
        run_role(
            role=Role.SCREENWRITER,
            ctx=sw_ctx,
            user_prompt="Write scene",
            output_schema=ScreenwriterOutput,
            mock_llm=mock_bad,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Milestone 5: Reference Budgeter & Jinja2 Prompt Compiler
# ─────────────────────────────────────────────────────────────────────────────


def test_reference_budgeter_and_prompt_compiler_determinism(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    _seed_valid_graph(tmp_repo)

    # Add 2 more characters in shot_1 to test 3-character + location + prop overcrowding
    for cid, cname in [("char_meera", "Meera"), ("char_vikram", "Vikram")]:
        tmp_repo.put_entity(
            Entity(
                id=cid,
                created_by=Role.SCRIPT_SUPERVISOR,
                entity_type=EntityType.CHARACTER,
                canonical_name=cname,
            )
        )
        app_c = tmp_repo.add_appearance(
            Appearance(
                id=f"app_{cid}_default",
                created_by=Role.CHARACTER_DESIGNER,
                status=Status.APPROVED,
                entity_id=cid,
                state_label="default",
                visual_description=f"{cname} distinctive visual look",
                wardrobe="dark blazer",
            )
        )
        img_bytes = MockImageGenerator().generate(f"Sheet for {cname}", seed=11)
        uri = tmp_repo.blobs.put_bytes(f"assets/{app_c.id}.png", img_bytes, "image/png")
        ast_c = tmp_repo.add_asset(
            Asset(
                id=f"ast_{cid}_default",
                created_by=Role.CHARACTER_DESIGNER,
                status=Status.APPROVED,
                kind="character_sheet",
                uri=uri,
                sha256="sha_" + cid,
                depicts_entity_ids=[cid],
                appearance_ids=[app_c.id],
                generation_prompt="sheet",
                model="mock",
            )
        )
        tmp_repo.update_appearance_status(
            app_c.id, Status.APPROVED, asset_ids=[ast_c.id]
        )

    shot = tmp_repo.get_shot("shot_1")
    assert shot is not None
    tmp_repo.put_shot(
        shot.model_copy(
            update={
                "cast": [
                    CastInShot(entity_id="char_arjun", framing="CU", speaking=True),
                    CastInShot(entity_id="char_meera", framing="CU", speaking=True),
                    CastInShot(entity_id="char_vikram", framing="MS", speaking=False),
                ]
            }
        )
    )

    sv = shot_view(tmp_repo, "shot_1")

    # Case A: max_reference_images = 3 -> reserves 1 location slot, composites top 2 speaking characters!
    caps_3 = default_cfg.video.model_copy(update={"max_reference_images": 3})
    plan_3 = select_references(sv, default_cfg, caps=caps_3, repo=tmp_repo)
    assert len(plan_3.selected_assets) <= 3
    assert len(plan_3.composites_to_build) == 1
    assert any(a.kind == "composite_sheet" for a in plan_3.selected_assets)
    assert any(a.kind == "location_plate" for a in plan_3.selected_assets)

    # Case B: max_reference_images = 0 -> all candidates dropped to verbal
    caps_0 = default_cfg.video.model_copy(update={"max_reference_images": 0})
    plan_0 = select_references(sv, default_cfg, caps=caps_0, repo=tmp_repo)
    assert plan_0.selected_assets == []
    assert len(plan_0.dropped_to_verbal) == 5

    # Determinism & hash stability across 10 runs
    pkgs = [
        compile_shot(sv, plan_3, default_cfg, caps=caps_3, project_id="test_proj")
        for _ in range(10)
    ]
    assert len({p.package_hash for p in pkgs}) == 1
    assert "STYLE:" in pkgs[0].compiled_prompt
    assert "SETTING:" in pkgs[0].compiled_prompt
    assert "ACTION:" in pkgs[0].compiled_prompt
    assert "DIALOGUE:" in pkgs[0].compiled_prompt
    assert 'Arjun (natural): "The compass points north."' in pkgs[0].compiled_prompt

    # PromptTooLong when cap is tiny
    tiny_caps = default_cfg.video.model_copy(update={"max_prompt_chars": 80})
    with pytest.raises(PromptTooLong):
        compile_shot(sv, plan_3, default_cfg, caps=tiny_caps, project_id="test_proj")


# ─────────────────────────────────────────────────────────────────────────────
# Milestone 6: End-to-End Pipeline S0..S10, Gates, Retries & FastAPI Service
# ─────────────────────────────────────────────────────────────────────────────


def test_end_to_end_pipeline_gates_retries_and_idempotency(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    story = (
        "Detective Arjun enters the rain-lit corner cafe in a trenchcoat carrying a brass compass. "
        "He meets Dr. Meera at the table. Later, Arjun steps onto the monsoon skyline rooftop in a formal suit."
    )
    vlm = MockVLMProvider(fail_shots_once={"shot_scn_001_01"})
    video_gen = MockVideoGenerator(caps=default_cfg.video)
    pipe = Pipeline(
        repo=tmp_repo,
        cfg=default_cfg,
        image_gen=MockImageGenerator(),
        video_gen=video_gen,
        vlm=vlm,
    )

    # 1. Run until Gate G1 blocks after S1_EXTRACT
    with pytest.raises(GateBlocked) as exc_g1:
        pipe.run_until_gate_or_done(story_text=story, auto_approve_gates=False)
    assert exc_g1.value.gate_id == "G1"
    assert len(tmp_repo.list_entities(EntityType.CHARACTER)) >= 2
    assert len(tmp_repo.list_entities(EntityType.LOCATION)) >= 2
    assert len(tmp_repo.list_entities(EntityType.OBJECT)) >= 1

    # 2. Approve G1 -> runs S2_SCREENPLAY and S3_DESIGN, then blocks at Gate G2
    approve_gate(tmp_repo, "G1")
    with pytest.raises(GateBlocked) as exc_g2:
        pipe.run_until_gate_or_done()
    assert exc_g2.value.gate_id == "G2"
    assert len(tmp_repo.list_appearances()) >= 4
    assert len(tmp_repo.list_assets()) >= 4

    # 3. Approve G2 -> runs S4_SHOTS and S5_MUSIC, then blocks at Gate G3
    approve_gate(tmp_repo, "G2")
    with pytest.raises(GateBlocked) as exc_g3:
        pipe.run_until_gate_or_done()
    assert exc_g3.value.gate_id == "G3"
    assert len(tmp_repo.list_shots()) >= 4

    # 4. Approve G3 -> runs S6_VALIDATE, S7_COMPILE, S8_RENDER (with retry on shot_scn_001_01!), S9_QA, S10_ASSEMBLE
    approve_gate(tmp_repo, "G3")
    completed_runs = pipe.run_until_gate_or_done()
    assert any(
        sr.stage == str(Stage.S10_ASSEMBLE) and sr.completed for sr in completed_runs
    )

    # Verify shot_scn_001_01 had 2 attempts (1st failed QA, 2nd passed QA)
    s1_runs = tmp_repo.list_generation_runs(shot_id="shot_scn_001_01")
    assert len(s1_runs) == 2
    assert s1_runs[0].status == Status.FAILED
    assert s1_runs[1].status == Status.APPROVED

    # Verify idempotency: re-running S8_RENDER when all shots are clean makes 0 new video_gen calls
    calls_before = len(video_gen.calls)
    pipe.run_stage(Stage.S8_RENDER, force=True)
    assert len(video_gen.calls) == calls_before


def test_budget_exceeded_cap(tmp_repo: Repo, default_cfg: Config) -> None:
    default_cfg.caps.stage_token_cap = 10  # tiny token cap
    pipe = Pipeline(repo=tmp_repo, cfg=default_cfg)
    with pytest.raises(BudgetExceeded):
        pipe.run_until_gate_or_done(
            story_text="Arjun walks into the rain-lit cafe with a brass compass.",
            auto_approve_gates=True,
        )


def test_fastapi_productions_service_endpoints() -> None:
    client = TestClient(app)

    # Health check
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["service"] == "veo-generators-productions"

    # Create a new production
    res_create = client.post(
        "/api/v1/productions",
        json={
            "name": "Monsoon Protocol",
            "type": "movie",
            "base_concept": "Detective Arjun meets Dr. Meera at a rain-lit cafe with a brass compass.",
            "video_length": "16",
            "orientation": "16:9",
            "language": "en-IN",
            "auto_approve_gates": False,
        },
    )
    assert res_create.status_code == 200
    prod = res_create.json()
    pid = prod["id"]

    # Run pipeline -> stops at G1
    res_run1 = client.post(f"/api/v1/productions/{pid}/run")
    assert res_run1.status_code == 200
    snap1 = res_run1.json()
    assert snap1["blocked_gate"] == "G1"
    assert len(snap1["story_graph"]["entities"]["characters"]) >= 2

    # Approve G1 -> advances through S2 & S3 and stops at G2
    res_g1 = client.post(f"/api/v1/productions/{pid}/gates/G1/approve")
    assert res_g1.status_code == 200
    snap2 = res_g1.json()
    assert snap2["blocked_gate"] == "G2"
    assert len(snap2["story_graph"]["appearances"]) >= 3

    # Approve G2 -> advances through S4 & S5 and stops at G3
    res_g2 = client.post(f"/api/v1/productions/{pid}/gates/G2/approve")
    assert res_g2.status_code == 200
    snap3 = res_g2.json()
    assert snap3["blocked_gate"] == "G3"
    shots = snap3["story_graph"]["shots"]
    assert len(shots) >= 2

    # Preview compiled prompt for the first shot
    first_shot_id = shots[0]["id"]
    res_compile = client.post(
        f"/api/v1/productions/{pid}/shots/{first_shot_id}/compile"
    )
    assert res_compile.status_code == 200
    compiled = res_compile.json()
    assert "STYLE:" in compiled["compiled_prompt"]
    assert compiled["package_hash"]

    # Approve G3 -> completes S6, S7, S8, S9, S10_ASSEMBLE
    res_g3 = client.post(f"/api/v1/productions/{pid}/gates/G3/approve")
    assert res_g3.status_code == 200
    snap_done = res_g3.json()
    assert snap_done["status"] == "completed"
    assert snap_done["final_video_url"]
