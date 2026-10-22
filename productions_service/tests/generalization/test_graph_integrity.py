"""Graph integrity report: contradictions, lifecycle gaps, orphans, raw ids, entries."""

from __future__ import annotations

from storygraph.graph_integrity import build_integrity_report, record_integrity_report
from storygraph.repo import Repo
from storygraph.schema import Entity, EntityType, Event, Role, StateEffect
from storygraph.state import rebuild_state_facts
from two_location_seed import HELPER, HERO, LANTERN, seed_two_locations


def test_integrity_report_finds_defects_and_notes_implicit_entries(
    tmp_repo: Repo,
) -> None:
    seed_two_locations(tmp_repo)
    tmp_repo.put_entity(
        Entity(
            id="obj_map",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.OBJECT,
            canonical_name="Map",
        )
    )
    tmp_repo.put_entity(
        Entity(
            id="obj_unused",
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=EntityType.OBJECT,
            canonical_name="Unused",
        )
    )
    shot = tmp_repo.get_shot("shot_2_2")
    assert shot is not None
    tmp_repo.put_shot(shot.model_copy(update={"prop_ids": ["obj_map"]}))
    tmp_repo.put_event(
        Event(
            id="evt_9", created_by=Role.SCRIPT_SUPERVISOR, story_order=22, scene_id="scn_2",
            summary="char_helper grabs the lantern", participants=[HELPER],
            effects=[
                StateEffect(entity_id=HELPER, attribute="holding", new_value=LANTERN),
                StateEffect(entity_id=HELPER, attribute="mood", new_value="calm"),
                StateEffect(entity_id=HELPER, attribute="mood", new_value="tense"),
            ],
        )
    )  # fmt: skip
    rebuild_state_facts(tmp_repo)
    rep = build_integrity_report(tmp_repo)
    kinds = {(f.kind, f.node_id) for f in rep.findings}
    assert ("contradiction", "evt_9") in kinds  # mood set twice in one Event
    assert ("contradiction", LANTERN) in kinds  # held by hero and helper at once
    assert ("no_lifecycle", "obj_map") in kinds
    assert ("orphan", "obj_unused") in kinds
    assert ("raw_id", "evt_9") in kinds
    assert ("implicit_entry", HERO) in kinds
    assert rep.stats["scene_entry_facts"] >= 2
    stored = record_integrity_report(tmp_repo)
    assert stored.stage == "S5_INTEGRITY" and stored.passed is False
    assert all(i.code.startswith("GI_") for i in stored.issues)
