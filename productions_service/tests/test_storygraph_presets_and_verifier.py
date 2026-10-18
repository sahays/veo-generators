"""Unit tests for StoryGraph creative presets, O(V+E) graph verifier, and stage QA remediation."""

from __future__ import annotations

from conftest import seed_valid_graph
from storygraph.agents.role import run_script_supervisor, run_story_architect
from storygraph.agents.stage_qa import list_stage_qa_reports, run_stage_qa_and_remediate
from storygraph.config import Config
from storygraph.graph_verifier import verify_storygraph
from storygraph.presets import (
    COLOR_PALETTE_PRESETS,
    DIRECTOR_STYLE_PRESETS,
    VISUAL_STYLE_PRESETS,
    resolve_production_presets,
)
from storygraph.repo import Repo
from storygraph.schema import Event, InteractionStep, ProjectMeta, Role, StateEffect
from storygraph.state import rebuild_state_facts, state_at
from storygraph.tools.registry import ToolContext
from storygraph.validate import validate_all


def test_presets_catalog_and_director_auto_binding() -> None:
    """Verify visual styles (Lego/Clay/Pixelated), color palettes, director last names, and O(1) auto-binding."""
    for visual_key in (
        "lego_brick",
        "clay_stopmotion",
        "pixelated_voxel",
        "pixar_3d",
        "ghibli_handpainted",
    ):
        assert visual_key in VISUAL_STYLE_PRESETS

    for palette_key in (
        "pastel_dreamy",
        "monochromatic_noir",
        "vibrant_pop",
        "warm_golden_amber",
    ):
        assert palette_key in COLOR_PALETTE_PRESETS

    expected_director_examples = {
        "wonder_spectacle": "Spielberg",
        "operatic_maximalism": "Bhansali",
        "cerebral_imax_tension": "Nolan",
        "kinetic_wit_chapters": "Tarantino",
        "clinical_symmetry": "Kubrick",
        "fast_cut_street_rhythm": "Ritchie",
    }
    for key, last_name in expected_director_examples.items():
        preset = DIRECTOR_STYLE_PRESETS[key]
        assert f"e.g., {last_name}" in preset.short_description

    resolved = resolve_production_presets(
        visual_style_id="lego_brick",
        color_palette_id="pastel_dreamy",
        director_style_id="cerebral_imax_tension",
    )
    assert resolved.visual_style.id == "lego_brick"
    assert resolved.color_palette.id == "pastel_dreamy"
    assert resolved.director_style.id == "cerebral_imax_tension"
    assert resolved.screenplay_style.id == "propulsive_puzzle"
    assert resolved.music_style.id == "braam_shepard_pulse"


def test_verify_storygraph_and_stage_qa_remediation(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """Verify O(V+E) single-pass verifier and shift-left Stage QA auto-remediation."""
    story_text = "Detective Arjun enters the rain-lit corner cafe carrying a brass compass and greets Dr. Meera."
    tmp_repo.put_project_meta(
        ProjectMeta(
            id="proj_test_verifier",
            name="Test Verifier",
            type="movie",
            visual_style_preset="clay_stopmotion",
            color_palette_preset="pastel_dreamy",
            director_style_preset="wonder_spectacle",
            created_by=Role.PIPELINE,
        )
    )
    tmp_repo.put_source_text(story_text)
    run_story_architect(
        ToolContext(repo=tmp_repo, role=Role.STORY_ARCHITECT, cfg=default_cfg),
        story_text,
    )
    run_script_supervisor(
        ToolContext(repo=tmp_repo, role=Role.SCRIPT_SUPERVISOR, cfg=default_cfg),
        story_text,
    )
    s1_report = run_stage_qa_and_remediate(tmp_repo, default_cfg, "S1_EXTRACT")
    assert s1_report.passed is True

    scenes = tmp_repo.list_scenes()
    assert len(scenes) >= 1
    first_scene = scenes[0]
    compound_step = InteractionStep(
        step_index=1,
        actor_id="char_arjun",
        interaction_type="prop",
        target_id="obj_compass",
        action="Arjun opens the compass; then he runs outside into the storm",
        emotional_beat="tense",
    )
    tmp_repo.put_scene(
        first_scene.model_copy(update={"interaction_steps": [compound_step]})
    )

    pre_issues = verify_storygraph(tmp_repo, default_cfg, through_stage="S2_SCREENPLAY")
    assert any(i.code == "compound_interaction_step" for i in pre_issues)

    s2_report = run_stage_qa_and_remediate(tmp_repo, default_cfg, "S2_SCREENPLAY")
    assert s2_report.passed is True
    updated_scene = tmp_repo.get_scene(first_scene.id)
    assert updated_scene is not None
    assert all(";" not in step.action for step in updated_scene.interaction_steps)

    reports = list_stage_qa_reports(tmp_repo)
    assert len(reports) >= 2


def test_sublocation_event_effects_remediation(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """Verify non-canonical event location strings ('countertop', 'floor near doorway') self-heal for V3/V4."""
    shot = seed_valid_graph(tmp_repo)
    tmp_repo.put_event(
        Event(
            id="evt_subloc",
            created_by=Role.SCRIPT_SUPERVISOR,
            story_order=12,
            scene_id=shot.scene_id,
            summary="Arjun places compass on countertop and stands near doorway",
            participants=["char_arjun"],
            effects=[
                StateEffect(
                    entity_id="char_arjun", attribute="holding", new_value=None
                ),
                StateEffect(
                    entity_id="obj_compass",
                    attribute="location",
                    new_value="countertop",
                ),
                StateEffect(
                    entity_id="char_arjun",
                    attribute="location",
                    new_value="floor near doorway",
                ),
            ],
        )
    )
    rebuild_state_facts(tmp_repo)
    pre_val = [i for i in validate_all(tmp_repo, default_cfg) if i.severity == "error"]
    assert any(i.code == "V3" for i in pre_val) and any(i.code == "V4" for i in pre_val)

    s4_report = run_stage_qa_and_remediate(tmp_repo, default_cfg, "S4_SHOTS")
    assert s4_report.passed is True
    assert (
        state_at(tmp_repo, "obj_compass", shot.story_order)["location"]
        == shot.location_id
    )
    assert (
        state_at(tmp_repo, "obj_compass", shot.story_order)["sub_location"]
        == "countertop"
    )
    assert (
        state_at(tmp_repo, "char_arjun", shot.story_order)["location"]
        == shot.location_id
    )
    assert [
        i for i in validate_all(tmp_repo, default_cfg) if i.severity == "error"
    ] == []
