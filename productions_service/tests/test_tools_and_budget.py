"""Milestones 4 & 5: Role Permission Matrix, Repair Loop, Reference Budgeter & Prompt Compiler tests."""

from __future__ import annotations

import pytest
from conftest import seed_valid_graph
from storygraph.adapters.mock import MockImageGenerator, MockLLMClient
from storygraph.agents.roles import ScreenwriterOutput
from storygraph.agents.runner import run_role
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.errors import PermissionDenied, PromptTooLong, StructuredOutputError
from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
    Asset,
    AttributeVal,
    CastInShot,
    Entity,
    EntityType,
    Provenance,
    Role,
    Status,
)
from storygraph.tools import write_tools as wt
from storygraph.tools.registry import ROLE_SCOPE, ToolContext
from storygraph.views import shot_view


def test_role_permissions_architect_and_designers(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
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
            visual_description="Illegal location appearance",
        )


def test_role_permissions_location_object_and_from_text(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    ld_ctx = ToolContext(repo=tmp_repo, role=Role.LOCATION_DESIGNER, cfg=default_cfg)
    wt.set_location_attributes(
        ld_ctx, "loc_cafe", {"lighting": "warm tungsten"}, provenance="invented"
    )
    with pytest.raises(PermissionDenied):
        wt.set_character_attributes(
            ld_ctx, "char_arjun", {"build": "tall"}, provenance="invented"
        )

    od_ctx = ToolContext(repo=tmp_repo, role=Role.OBJECT_DESIGNER, cfg=default_cfg)
    wt.set_object_attributes(
        od_ctx, "obj_compass", {"material": "aged brass"}, provenance="invented"
    )
    with pytest.raises(PermissionDenied):
        wt.set_location_attributes(
            od_ctx, "loc_cafe", {"floor": "wood"}, provenance="invented"
        )

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
    cd_ctx = ToolContext(repo=tmp_repo, role=Role.CHARACTER_DESIGNER, cfg=default_cfg)
    with pytest.raises(PermissionDenied, match="FROM_TEXT"):
        wt.set_character_attributes(
            cd_ctx, "char_arjun", {"eyes": "blue"}, provenance="invented"
        )


def test_role_permissions_writers_director_music_and_critic(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    sw_ctx = ToolContext(repo=tmp_repo, role=Role.SCREENWRITER, cfg=default_cfg)
    wt.update_scene_script(sw_ctx, "scn_1", summary="Updated summary", mood="noir")
    with pytest.raises(PermissionDenied):
        wt.put_entity(
            sw_ctx, entity_id="char_new", entity_type="character", canonical_name="New"
        )

    dir_ctx = ToolContext(repo=tmp_repo, role=Role.DIRECTOR, cfg=default_cfg)
    with pytest.raises(PermissionDenied):
        wt.put_dialogue(
            dir_ctx,
            line_id="dlg_illegal",
            scene_id="scn_1",
            order_in_scene=2,
            speaker_id="char_arjun",
            text="Illegal",
        )

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
    cr_ctx = ToolContext(repo=tmp_repo, role=Role.CRITIC, cfg=default_cfg)
    wt.create_change_request(
        cr_ctx, to_role=Role.DIRECTOR, target_node_id="shot_1", reason="Fix framing"
    )
    assert len(tmp_repo.list_audit_entries()) >= 3 and len(ROLE_SCOPE) >= 10


def test_structured_output_repair_loop(tmp_repo: Repo, default_cfg: Config) -> None:
    sw_ctx = ToolContext(repo=tmp_repo, role=Role.SCREENWRITER, cfg=default_cfg)
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


def _seed_extra_cast_for_budgeter(tmp_repo: Repo) -> None:
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
                visual_description=f"{cname} look",
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


def test_reference_budgeter_and_prompt_compiler_determinism(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    _seed_extra_cast_for_budgeter(tmp_repo)
    cast = [
        CastInShot(entity_id="char_arjun", framing="CU", speaking=True),
        CastInShot(entity_id="char_meera", framing="CU", speaking=True),
        CastInShot(entity_id="char_vikram", framing="MS", speaking=False),
    ]
    tmp_repo.put_shot(shot.model_copy(update={"cast": cast}))
    sv = shot_view(tmp_repo, "shot_1")
    caps_3 = default_cfg.video.model_copy(update={"max_reference_images": 3})
    plan_3 = select_references(sv, default_cfg, caps=caps_3, repo=tmp_repo)
    assert len(plan_3.selected_assets) <= 3 and len(plan_3.composites_to_build) == 1
    assert any(a.kind == "composite_sheet" for a in plan_3.selected_assets)
    assert any(a.kind == "location_plate" for a in plan_3.selected_assets)

    caps_0 = default_cfg.video.model_copy(update={"max_reference_images": 0})
    plan_0 = select_references(sv, default_cfg, caps=caps_0, repo=tmp_repo)
    assert plan_0.selected_assets == [] and len(plan_0.dropped_to_verbal) == 5

    pkgs = [
        compile_shot(sv, plan_3, default_cfg, caps=caps_3, project_id="test_proj")
        for _ in range(5)
    ]
    assert len({p.package_hash for p in pkgs}) == 1
    assert 'Arjun (natural): "The compass points north."' in pkgs[0].compiled_prompt
    tiny_caps = default_cfg.video.model_copy(update={"max_prompt_chars": 80})
    with pytest.raises(PromptTooLong):
        compile_shot(sv, plan_3, default_cfg, caps=tiny_caps, project_id="test_proj")
