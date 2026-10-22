"""Unit tests for StoryGraph creative presets, O(V+E) graph verifier, and stage QA remediation."""

from __future__ import annotations

from conftest import add_clip_shot, seed_valid_graph, set_scene_clips
from storygraph.agents.critic import _collect_qa_failures, _normalize_qa_report
from storygraph.agents.role import run_script_supervisor, run_story_architect
from storygraph.agents.stage_qa import list_stage_qa_reports, run_stage_qa_and_remediate
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.graph_verifier import verify_storygraph
from storygraph.omni.spec import OmniClipSpec
from storygraph.physics import remediate_physical_causality
from storygraph.pipeline import Pipeline, Stage
from storygraph.presets import (
    COLOR_PALETTE_PRESETS,
    DIRECTOR_STYLE_PRESETS,
    VISUAL_STYLE_PRESETS,
    resolve_production_presets,
)
from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
    Entity,
    EntityType,
    Event,
    InteractionStep,
    ProjectMeta,
    QAReport,
    Role,
    StateEffect,
    Status,
)
from storygraph.state import rebuild_state_facts, state_at
from storygraph.tools import write_tools as wt
from storygraph.tools.registry import ToolContext
from storygraph.validate import validate_all
from storygraph.views import shot_view


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


def test_physical_causality_and_backward_prop_liveness_closure(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """Verify Hoare-triple state enrichment, backward prop liveness closure, and physics prompt compilation."""
    shot1 = seed_valid_graph(tmp_repo)
    scene = tmp_repo.get_scene(shot1.scene_id)
    assert scene is not None
    step1 = InteractionStep(
        step_index=1,
        actor_id="char_arjun",
        interaction_type="prop",
        target_id="obj_compass",
        action="Arjun reaches out and places the brass compass onto the wooden table",
        emotional_beat="focused",
    )
    step2 = step1.model_copy(
        update={
            "step_index": 2,
            "action": "Arjun inspects the brass compass on the table",
        }
    )
    tmp_repo.put_scene(
        scene.model_copy(
            update={
                "interaction_steps": [step1, step2],
                "shot_ids": [shot1.id, "shot_002"],
            }
        )
    )
    set_scene_clips(tmp_repo, scene.id, [[1], [2]])
    tmp_repo.put_shot(shot1.model_copy(update={"prop_ids": []}))
    add_clip_shot(tmp_repo, shot1, "shot_002", 2, 25)

    issues = verify_storygraph(tmp_repo, default_cfg, through_stage="S4_SHOTS")
    codes = {i.code for i in issues}
    assert "missing_step_physics_state" in codes
    assert "prop_permanence_gap" in codes

    s4_report = run_stage_qa_and_remediate(tmp_repo, default_cfg, "S4_SHOTS")
    assert s4_report.passed is True

    healed_shot1 = tmp_repo.get_shot(shot1.id)
    assert healed_shot1 is not None and "obj_compass" in healed_shot1.prop_ids
    healed_scene = tmp_repo.get_scene(scene.id)
    assert healed_scene is not None
    enriched_step = healed_scene.interaction_steps[0]
    assert enriched_step.pre_state and enriched_step.post_state
    assert "Cafe" in enriched_step.supported_by

    view1 = shot_view(tmp_repo, shot1.id)
    plan1 = select_references(view1, default_cfg)
    pkg1 = compile_shot(view1, plan1, default_cfg)
    assert "Brass Compass" in pkg1.compiled_prompt
    assert "PHYSICS" not in pkg1.compiled_prompt
    assert "AVOID" not in pkg1.compiled_prompt


def test_critic_physics_and_permanence_qa_rejection(default_cfg: Config) -> None:
    """Verify Critic S9 QA flags materialization, inversion, floating objects, and low physics/permanence scores."""
    raw = QAReport(
        passed=True,
        wardrobe_match=0.95,
        setting_match=0.95,
        action_achieved=0.90,
        physics_plausibility=0.50,
        object_permanence=0.40,
        artifact_flags=["object_materialized", "prop_inverted", "floating_object"],
    )
    norm, severe = _normalize_qa_report(raw, default_cfg, is_mock=False)
    assert {
        "object_materialized",
        "prop_inverted",
        "floating_object",
    }.issubset(severe)
    failures = _collect_qa_failures(
        norm, default_cfg, is_mock=False, severe_flags=severe
    )
    assert any("Physics plausibility" in f for f in failures)
    assert any("Object permanence" in f for f in failures)
    assert any("object_materialized" in f for f in failures)
    assert any("prop_inverted" in f for f in failures)


def test_auto_mode_and_iterative_agent_review_redo_before_render(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """Verify auto_approve_gates defaults to True and S6_VALIDATE redoes upstream agent stages when issues exist."""
    meta = ProjectMeta(
        id="p_auto",
        name="Auto Mode Test",
        base_concept="Pip pulls a wooden chair to the kitchen table and climbs up.",
        story_text="Pip pulls a wooden chair to the kitchen table and climbs up.",
    )
    assert meta.auto_approve_gates is True
    tmp_repo.put_project_meta(meta)

    pipe = Pipeline(repo=tmp_repo, cfg=default_cfg)
    for st in (
        Stage.S1_EXTRACT,
        Stage.S2_SCREENPLAY,
        Stage.S3_DESIGN,
        Stage.S4_SHOTS,
        Stage.S5_MUSIC,
    ):
        pipe.run_stage(st)

    for sh in tmp_repo.list_shots():
        tmp_repo.store.delete("shots", sh.id)
    critic_ctx = ToolContext(repo=tmp_repo, role=Role.CRITIC, cfg=default_cfg)
    wt.create_change_request(
        critic_ctx,
        to_role=Role.DIRECTOR,
        target_node_id="scn_001",
        reason="Missing shot breakdown for scene; redo S4_SHOTS",
        proposed_patch={"action": "redo_shots"},
    )
    assert len(tmp_repo.list_shots()) == 0
    assert len(tmp_repo.list_change_requests(open_only=True)) == 1

    pipe.run_stage(Stage.S6_VALIDATE, force=True)
    assert len(tmp_repo.list_shots()) >= 1
    assert len(tmp_repo.list_change_requests(open_only=True)) == 0


def test_archetype_conservation_voice_lock_and_critic_flags(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """Verify data-driven prop states per clip, character permanence closure, voice, and QA flags."""
    shot1 = seed_valid_graph(tmp_repo)
    for eid, etype, name, desc in (
        ("char_milo", EntityType.CHARACTER, "Milo", "Playful golden puppy"),
        (
            "obj_chair",
            EntityType.OBJECT,
            "Wooden Chair",
            "Four-legged wooden chair with tall backrest",
        ),
        ("obj_towel", EntityType.OBJECT, "Kitchen Towel", "Checkered cloth towel"),
        ("obj_bowl", EntityType.OBJECT, "Mixing Bowl", "Ceramic mixing bowl"),
    ):
        tmp_repo.put_entity(
            Entity(
                id=eid,
                entity_type=etype,
                canonical_name=name,
                description=desc,
                created_by=Role.STORY_ARCHITECT,
            )
        )
        app_node = tmp_repo.add_appearance(
            Appearance(
                id=f"app_{eid}_default",
                created_by=Role.DESIGNER,
                status=Status.APPROVED,
                entity_id=eid,
                state_label="default",
                visual_description=desc,
            )
        )
        tmp_repo.update_appearance_status(
            app_node.id,
            Status.APPROVED,
            asset_ids=["ast_char_arjun_trenchcoat_v1"],
        )
    scene = tmp_repo.get_scene(shot1.scene_id)
    assert scene is not None
    steps = [
        InteractionStep(
            step_index=1,
            actor_id="char_arjun",
            interaction_type="prop",
            target_id="obj_chair",
            action="walks to the wooden chair, pulls it beside the counter, and steps onto the seat",
        ),
        InteractionStep(
            step_index=2,
            actor_id="char_arjun",
            interaction_type="prop",
            target_id="obj_towel",
            action="pulls the hanging kitchen towel into his hand",
        ),
        InteractionStep(
            step_index=3,
            actor_id="char_arjun",
            interaction_type="prop",
            target_id="obj_bowl",
            action="sets down the mixing bowl on the kitchen counter",
        ),
        InteractionStep(
            step_index=4,
            actor_id="char_milo",
            interaction_type="prop",
            target_id="obj_chair",
            action="returns the wooden chair to its original position beside the table",
        ),
    ]
    set_scene_clips(tmp_repo, scene.id, [[1, 2], [3, 4]], steps)
    add_clip_shot(tmp_repo, shot1, "shot_1b", 2, 16)
    issues = verify_storygraph(tmp_repo, default_cfg, through_stage="S4_SHOTS")
    codes = {i.code for i in issues}
    assert "character_permanence_gap" in codes
    # The scene-wide prop closure is advisory now: props are scoped per clip at view time.
    assert all(i.severity == "warn" for i in issues if i.code == "prop_permanence_gap")

    remediate_physical_causality(tmp_repo, [], include_shots=True)
    healed_shot1 = tmp_repo.get_shot(shot1.id)
    assert healed_shot1 is not None
    assert "char_milo" in {c.entity_id for c in healed_shot1.cast}

    view1 = shot_view(tmp_repo, shot1.id)
    plan1 = select_references(view1, default_cfg)
    pkg1 = compile_shot(view1, plan1, default_cfg)
    assert "NEVER" not in pkg1.compiled_prompt
    # Clip 1 moves the chair and towel; the bowl is only touched in clip 2, so it is absent.
    spec = OmniClipSpec.model_validate_json(pkg1.spec_json)
    moves = {o.name: o.moves for o in spec.objects or []}
    assert (
        moves["Wooden Chair"] and moves["Kitchen Towel"] and "Mixing Bowl" not in moves
    )

    raw_qa = QAReport(
        passed=True,
        artifact_flags=[
            "start_frame_bleed",
            "duplicate_prop",
            "prop_part_missing",
            "self_moving_object",
        ],
    )
    _, severe = _normalize_qa_report(raw_qa, default_cfg, is_mock=False)
    assert {
        "start_frame_bleed",
        "duplicate_prop",
        "prop_part_missing",
        "self_moving_object",
    }.issubset(severe)
