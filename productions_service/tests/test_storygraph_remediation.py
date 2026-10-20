"""Regression tests for the 6 StoryGraph remediation workstreams (Aranya Kand audit fixes)."""

from __future__ import annotations

import dataclasses

from conftest import seed_valid_graph
from storygraph.adapters.gemini_video import _build_omni_input_blocks
from storygraph.adapters.mock import MockVLMProvider
from storygraph.agents.critic import _normalize_qa_report, evaluate_clip_qa
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.omni.spec import OmniClipSpec
from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
    Asset,
    CastInShot,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    GenerationRun,
    QAReport,
    Role,
    Scene,
    StateEffect,
    Status,
)
from storygraph.state import (
    appearance_for,
    normalize_scene_timeline,
    rebuild_state_facts,
    state_at,
)
from storygraph.tools.role_helpers.models import ShotDraft
from storygraph.tools.role_helpers.normalization import (
    deduplicate_cast_positions,
    partition_scene_dialogues,
)
from storygraph.validate import validate_shot
from storygraph.views import shot_view


def _seed_shabari_scene_nodes(repo: Repo) -> None:
    """Seed Scene 3 (`scn_003`), `char_shabari`, `obj_berries`, and approved assets."""
    for eid, etype, name, kind in [
        ("char_shabari", EntityType.CHARACTER, "Shabari", "character_sheet"),
        ("obj_berries", EntityType.OBJECT, "Berries Basket", "prop_sheet"),
    ]:
        repo.put_entity(
            Entity(
                id=eid,
                created_by=Role.SCRIPT_SUPERVISOR,
                entity_type=etype,
                canonical_name=name,
            )
        )
        app = repo.add_appearance(
            Appearance(
                id=f"app_{eid}_default",
                created_by=Role.DESIGNER,
                status=Status.APPROVED,
                entity_id=eid,
                state_label="default",
                visual_description=f"{name} canonical visual appearance",
            )
        )
        uri = repo.blobs.put_bytes(f"assets/{app.id}.png", b"png", "image/png")
        ast = repo.add_asset(
            Asset(
                id=f"ast_{eid}_default",
                created_by=Role.DESIGNER,
                status=Status.APPROVED,
                kind=kind,
                uri=uri,
                sha256=f"sha_{app.id}",
                depicts_entity_ids=[eid],
                appearance_ids=[app.id],
                generation_prompt="p",
                model="mock",
            )
        )
        repo.update_appearance_status(app.id, Status.APPROVED, asset_ids=[ast.id])
    repo.put_scene(
        Scene(
            id="scn_003",
            created_by=Role.STORY_ARCHITECT,
            index=3,
            heading="EXT. HERMITAGE",
            location_id="loc_cafe",
            time_of_day="day",
        )
    )


def test_story_order_alignment(tmp_repo: Repo) -> None:
    base_shot = seed_valid_graph(tmp_repo)
    _seed_shabari_scene_nodes(tmp_repo)
    eff_3 = [
        StateEffect(
            entity_id="char_shabari", attribute="location", new_value="loc_cafe"
        ),
        StateEffect(
            entity_id="char_shabari", attribute="holding", new_value="obj_berries"
        ),
    ]
    eff_4 = [
        StateEffect(entity_id="char_arjun", attribute="location", new_value="loc_cafe")
    ]
    for eid, order, part, eff in [
        ("evt_03", 30, "char_shabari", eff_3),
        ("evt_04", 31, "char_arjun", eff_4),
    ]:
        tmp_repo.put_event(
            Event(
                id=eid,
                created_by=Role.SCRIPT_SUPERVISOR,
                story_order=order,
                scene_id="scn_003",
                summary="E",
                participants=[part],
                effects=eff,
            )
        )
    cast = [
        CastInShot(entity_id="char_shabari", position="left"),
        CastInShot(entity_id="char_arjun", position="right"),
    ]
    for idx in (1, 2):
        tmp_repo.put_shot(
            base_shot.model_copy(
                update={
                    "id": f"shot_scn_003_0{idx}",
                    "scene_id": "scn_003",
                    "index_in_scene": idx,
                    "story_order": 31,
                    "covers_event_ids": ["evt_03", "evt_04"],
                    "cast": cast,
                    "prop_ids": ["obj_berries"],
                }
            )
        )
    normalize_scene_timeline(tmp_repo)
    rebuild_state_facts(tmp_repo)
    s1, s2 = tmp_repo.get_shot("shot_scn_003_01"), tmp_repo.get_shot("shot_scn_003_02")
    assert (
        s1 is not None
        and s1.story_order == 30
        and s2 is not None
        and s2.story_order == 31
    )
    assert (
        state_at(tmp_repo, "char_shabari", s1.story_order)["holding"] == "obj_berries"
    )
    assert (
        shot_view(tmp_repo, "shot_scn_003_01").cast_states["char_shabari"]["holding"]
        == "obj_berries"
    )


def test_dialogue_partitioning_and_speaker_binding(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    base_shot = seed_valid_graph(tmp_repo)
    _seed_shabari_scene_nodes(tmp_repo)
    raw = [
        ("dlg_s1", 1, "char_shabari", "Welcome to the forest hermitage, traveler."),
        ("dlg_s2", 2, "char_arjun", "Thank you for these sweet forest berries."),
        ("dlg_s3", 3, "char_shabari", "I tasted each one so only the sweetest remain."),
    ]
    lines = [
        tmp_repo.put_dialogue(
            DialogueLine(
                id=did,
                created_by=Role.SCREENWRITER,
                scene_id="scn_1",
                order_in_scene=idx,
                speaker_id=spk,
                text=txt,
            )
        )
        for did, idx, spk, txt in raw
    ]
    drafts = [
        ShotDraft(
            shot_id="s1",
            index_in_scene=1,
            story_order=10,
            covers_event_ids=["evt_1"],
            location_id="loc_cafe",
            dialogue_ids=["dlg_s1", "dlg_s2", "dlg_s3"],
        ),
        ShotDraft(
            shot_id="s2",
            index_in_scene=2,
            story_order=11,
            covers_event_ids=["evt_2"],
            location_id="loc_cafe",
            dialogue_ids=[],
        ),
    ]
    buckets = partition_scene_dialogues(
        drafts, [d.id for d in lines], {d.id: d for d in lines}
    )
    assert [did for b in buckets for did in b] == ["dlg_s1", "dlg_s2", "dlg_s3"]
    assert len(buckets[0]) == 2 and len(buckets[1]) == 1
    cast = [
        CastInShot(
            entity_id="char_shabari",
            appearance_id="app_char_shabari_default_v1",
            position="left",
            speaking=True,
        ),
        CastInShot(
            entity_id="char_arjun",
            appearance_id="app_char_arjun_trenchcoat_v1",
            position="right",
            speaking=False,
        ),
    ]
    tmp_repo.put_shot(
        base_shot.model_copy(update={"cast": cast, "dialogue_ids": ["dlg_s1"]})
    )
    sv = shot_view(tmp_repo, "shot_1")
    pkg = compile_shot(
        sv, select_references(sv, default_cfg, repo=tmp_repo), default_cfg
    )
    spec = OmniClipSpec.model_validate_json(pkg.compiled_prompt)
    subj = {s.name: s for s in spec.subjects or []}
    speakers = {s.speaker for s in spec.speech or []}
    shabari = next(s for s in subj.values() if s.screen_pos == "left")
    assert speakers == {shabari.id} and shabari.framing == "MS"
    assert "lipsync_active_speaker_only" in spec.constraints


def test_compile_budget_preserves_identity_and_props(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    long_id = (
        "Young prince with warm expressive dark eyes, dark arched eyebrows, "
        "rounded cheeks, serene smile, and soft pastel cotton-candy blue skin."
    )
    minted = tmp_repo.add_appearance(
        appearance_for(tmp_repo, "char_arjun", 15).model_copy(
            update={"visual_description": long_id}
        )
    )
    tmp_repo.put_shot(
        shot.model_copy(
            update={
                "cast": [
                    c.model_copy(update={"appearance_id": minted.id}) for c in shot.cast
                ]
            }
        )
    )
    sv = shot_view(tmp_repo, "shot_1")
    plan = select_references(sv, default_cfg, repo=tmp_repo)
    plan.dropped_to_verbal = ["Brass Compass: antique weathered pocket compass"]
    caps = default_cfg.video.model_copy(update={"max_prompt_chars": 950})
    pkg = compile_shot(sv, plan, default_cfg, caps=caps)
    full = compile_shot(sv, plan, default_cfg)
    spec = OmniClipSpec.model_validate_json(pkg.compiled_prompt)
    whole = OmniClipSpec.model_validate_json(full.compiled_prompt)
    assert len(pkg.compiled_prompt) < len(full.compiled_prompt)
    assert "cotton-candy blue" in full.compiled_prompt  # trimmed only under budget
    assert spec.sequence == whole.sequence and spec.speech == whole.speech
    assert "Brass Compass" in {o.name for o in spec.objects or []}


def test_first_frame_slot_reservation_and_ordering(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    base_shot = seed_valid_graph(tmp_repo)
    _seed_shabari_scene_nodes(tmp_repo)
    ff_uri = tmp_repo.blobs.put_bytes("assets/lastframe.png", b"png", "image/png")
    ff_ast = tmp_repo.add_asset(
        Asset(
            id="ast_lf",
            created_by=Role.PIPELINE,
            status=Status.APPROVED,
            kind="first_frame",
            uri=ff_uri,
            sha256="sha",
            depicts_entity_ids=["char_arjun", "char_shabari"],
            generation_prompt="lf",
            model="ffmpeg",
        )
    )
    cast = [
        CastInShot(
            entity_id="char_arjun",
            appearance_id="app_char_arjun_trenchcoat_v1",
            position="left",
            speaking=True,
        ),
        CastInShot(
            entity_id="char_shabari",
            appearance_id="app_char_shabari_default_v1",
            position="right",
            speaking=False,
        ),
    ]
    tmp_repo.put_shot(
        base_shot.model_copy(
            update={
                "cast": cast,
                "prop_ids": ["obj_compass", "obj_berries"],
                "continue_from_last_frame": True,
            }
        )
    )
    sv = shot_view(tmp_repo, "shot_1").model_copy(
        update={"prev_shot_last_frame": ff_ast}
    )
    default_cfg.video.max_reference_images = 3
    plan = select_references(sv, default_cfg, repo=tmp_repo)
    assert plan.first_frame is not None and len(plan.selected_assets) <= 2
    pkg = dataclasses.replace(
        compile_shot(sv, plan, default_cfg),
        first_frame_uri="gs://b/lf.png",
        reference_uris=["gs://b/c.png", "gs://b/p.png"],
    )
    imgs = [
        b
        for b in _build_omni_input_blocks(pkg, pkg.compiled_prompt, max_refs=3)
        if b["type"] == "image"
    ]
    assert len(imgs) == 3 and imgs[0]["uri"] == "gs://b/lf.png"


def test_spatial_blocking_deduplication_and_continuity(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    _seed_shabari_scene_nodes(tmp_repo)
    colliding = [
        CastInShot(
            entity_id="char_arjun",
            appearance_id="app_char_arjun_trenchcoat_v1",
            position="center",
        ),
        CastInShot(
            entity_id="char_shabari",
            appearance_id="app_char_shabari_default_v1",
            position="center",
        ),
    ]
    issues = validate_shot(
        tmp_repo, shot.model_copy(update={"cast": colliding}), default_cfg
    )
    assert any(i.code == "cast_position_collision" for i in issues)
    deduped = deduplicate_cast_positions(
        {c.entity_id: c for c in colliding},
        prev_positions={"char_arjun": "left", "char_shabari": "right"},
    )
    assert (
        deduped["char_arjun"].position == "left"
        and deduped["char_shabari"].position == "right"
    )


def test_critic_rejects_missing_character_and_low_scores(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    mediocre = QAReport(
        face_similarity={"char_arjun": 0.50},
        wardrobe_match=0.50,
        setting_match=0.50,
        action_achieved=0.50,
        continuity_prev_shot=0.25,
        dialogue_wer=0.0,
        artifact_flags=["missing_character_lakshman", "skin_color_inconsistency"],
        passed=True,
    )
    norm_report, severe = _normalize_qa_report(mediocre, default_cfg, is_mock=False)
    assert norm_report.wardrobe_match == 0.50 and "missing_character_lakshman" in severe
    uri = tmp_repo.blobs.put_bytes("clips/fail.mp4", b"mp4", "video/mp4")
    run_node = tmp_repo.add_generation_run(
        GenerationRun(
            id="run_fail",
            created_by=Role.PIPELINE,
            status=Status.RENDERED,
            shot_id=shot.id,
            attempt=1,
            provider="mock",
            model="mock",
            compiled_prompt="p",
            negative_prompt="n",
            seed=42,
            package_hash="h",
            output_video_uri=uri,
        )
    )
    vlm = MockVLMProvider(custom_responder=lambda _i, _p, _s: mediocre)
    final_qa = evaluate_clip_qa(tmp_repo, default_cfg, vlm, shot, run_node)
    assert not final_qa.passed
    updated = next(
        (
            r
            for r in tmp_repo.list_generation_runs(shot_id=shot.id)
            if r.id == run_node.id
        ),
        None,
    )
    assert updated is not None and updated.extracted_last_frame_asset_id is not None
    lf_asset = tmp_repo.get_asset(updated.extracted_last_frame_asset_id)
    assert lf_asset is not None and lf_asset.status == Status.PROPOSED
