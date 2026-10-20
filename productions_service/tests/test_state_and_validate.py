"""Milestone 3: State Engine intervals and Validator rules V1 through V13 tests."""

from __future__ import annotations

from conftest import seed_valid_graph
from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.schema import (
    ActionBeat,
    CastInShot,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    Role,
    StateEffect,
)
from storygraph.state import appearance_for, rebuild_state_facts, state_at
from storygraph.validate import validate_all, validate_shot


def test_state_engine_intervals_and_valid_graph(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    assert state_at(tmp_repo, "char_arjun", 15)["wearing"] == "trenchcoat"
    assert state_at(tmp_repo, "char_arjun", 20)["wearing"] == "formal_suit"
    app_15 = appearance_for(tmp_repo, "char_arjun", 15)
    app_25 = appearance_for(tmp_repo, "char_arjun", 25)
    assert app_15 is not None and app_15.state_label == "trenchcoat"
    assert app_25 is not None and app_25.state_label == "formal_suit"
    assert validate_all(tmp_repo, default_cfg) == []


def test_validator_rules_v1_through_v4(tmp_repo: Repo, default_cfg: Config) -> None:
    shot = seed_valid_graph(tmp_repo)
    bad_v1 = shot.model_copy(update={"location_appearance_id": ""})
    assert any(i.code == "V1" for i in validate_shot(tmp_repo, bad_v1, default_cfg))
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
    bad_v3 = shot.model_copy(update={"location_id": "loc_other"})
    assert any(i.code == "V3" for i in validate_shot(tmp_repo, bad_v3, default_cfg))

    effs = [
        StateEffect(entity_id="char_arjun", attribute="holding", new_value=None),
        StateEffect(
            entity_id="obj_compass", attribute="location", new_value="loc_vault"
        ),
    ]
    tmp_repo.put_event(
        Event(
            id="evt_prop_move",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=12,
            scene_id="scn_1",
            summary="Arjun sets down compass in vault",
            participants=["char_arjun"],
            effects=effs,
        )
    )
    rebuild_state_facts(tmp_repo)
    assert any(i.code == "V4" for i in validate_shot(tmp_repo, shot, default_cfg))


def test_validator_rules_v5_and_v10_v12(tmp_repo: Repo, default_cfg: Config) -> None:
    shot = seed_valid_graph(tmp_repo)
    eff = [
        StateEffect(
            entity_id="char_arjun", attribute="alive_present", new_value="false"
        )
    ]
    tmp_repo.put_event(
        Event(
            id="evt_absent",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=14,
            scene_id="scn_1",
            summary="Arjun exits",
            participants=["char_arjun"],
            effects=eff,
        )
    )
    rebuild_state_facts(tmp_repo)
    assert any(i.code == "V5" for i in validate_shot(tmp_repo, shot, default_cfg))

    tmp_repo.put_entity(
        Entity(
            id="char_dup",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.CHARACTER,
            canonical_name="Arjun",
        )
    )
    tmp_repo.put_event(  # an event in a scene with no shots is covered by no clip
        Event(
            id="evt_orphan",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=90,
            scene_id="scn_unshot",
            summary="Unfilmed beat",
        )
    )
    all_issues = validate_all(tmp_repo, default_cfg)
    assert any(i.code == "V12" for i in all_issues)
    assert any(i.code == "V10" for i in all_issues)


def test_validator_rules_v6_through_v13(tmp_repo: Repo, default_cfg: Config) -> None:
    shot = seed_valid_graph(tmp_repo)
    bad_v6 = shot.model_copy(update={"duration_s": 12.0})
    assert any(i.code == "V6" for i in validate_shot(tmp_repo, bad_v6, default_cfg))

    beats = [
        ActionBeat(t_start_s=0.0, t_end_s=3.0, description="Beat 1"),
        ActionBeat(t_start_s=2.0, t_end_s=5.0, description="Overlapping Beat 2"),
    ]
    bad_v7 = shot.model_copy(update={"beats": beats})
    assert any(i.code == "V7" for i in validate_shot(tmp_repo, bad_v7, default_cfg))

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
    bad_v9 = shot.model_copy(update={"cast": []})
    assert any(i.code == "V9" for i in validate_shot(tmp_repo, bad_v9, default_cfg))
    bad_v11 = shot.model_copy(update={"continue_from_last_frame": True})
    assert any(
        i.code == "V11" and i.severity == "warn"
        for i in validate_shot(tmp_repo, bad_v11, default_cfg, prev_shot=None)
    )
    bad_v13 = shot.model_copy(update={"stale": True, "stale_reason": "test stale"})
    assert any(i.code == "V13" for i in validate_shot(tmp_repo, bad_v13, default_cfg))
