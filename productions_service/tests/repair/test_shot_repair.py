"""Automatic shot repair: diagnosis, escalation, bounded attempts, flagging, edits, continuity."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

import pytest
from conftest import seed_valid_graph, set_scene_clips
from storygraph.adapters.mock import (
    MockImageGenerator,
    MockVideoGenerator,
    MockVLMProvider,
)
from storygraph.assembly import evaluate_shot_readiness
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.errors import ValidationFailed
from storygraph.pipeline import Pipeline, Stage
from storygraph.pipeline.render_stage import render_single_shot_with_qa
from storygraph.qa.retry_rewrite import BANNED_RE, PropFocus, RewriteContext
from storygraph.repair import FailureClass, diagnose_failure
from storygraph.repair.clip_edit import ClipEdit, edit_shot_clip
from storygraph.repair.loop import regenerate_shot, repair_failed_shots
from storygraph.repo import Repo
from storygraph.schema import InteractionStep, QAReport, Shot
from storygraph.views import shot_view

_ORIGINAL_QA = MockVLMProvider._build_qa_report
_LIVE_FLAGS = [
    "object_materialized",
    "object_vanished",
    "character_design_drift:Arjun",
    "action_teleportation",
    "spatial_axis_flip",
]
_CTX = RewriteContext(
    actors=("Arjun",),
    props=(PropFocus("Brass Compass", "Arjun"),),
    sides=(("Arjun", "center"),),
    actor_keys={"arjun": "Arjun"},
)


def _failed_qa() -> QAReport:
    return QAReport(
        passed=False,
        action_achieved=0.4,
        object_permanence=0.5,
        artifact_flags=list(_LIVE_FLAGS),
        failure_reasons=["the compass vanishes mid-shot", "Arjun's eyes change shape"],
        suggested_fix="retry_seed",
    )


@pytest.fixture()
def qa_script(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, list[bool]]]:
    """Per-shot scripted QA verdicts (True = pass); unscripted renders pass."""
    script: dict[str, list[bool]] = {}

    def _scripted(self: MockVLMProvider, prompt: str) -> QAReport:
        match = re.search(r"shot_id=([A-Za-z0-9_]+)", prompt)
        seq = script.get(match.group(1) if match else "", [])
        if seq and not seq.pop(0):
            return _failed_qa()
        return _ORIGINAL_QA(MockVLMProvider(), prompt)

    monkeypatch.setattr(MockVLMProvider, "_build_qa_report", _scripted)
    yield script


def _shot(repo: Repo, shot_id: str = "shot_1") -> Shot:
    shot = repo.get_shot(shot_id)
    assert shot is not None
    return shot


def _video(cfg: Config) -> MockVideoGenerator:
    return MockVideoGenerator(caps=cfg.video)


def test_diagnose_maps_live_flags_to_targeted_directive(default_cfg: Config) -> None:
    d = diagnose_failure(_failed_qa(), _CTX, default_cfg.qa, attempt=1)
    assert d.failure_classes == [
        FailureClass.IDENTITY_DRIFT,
        FailureClass.OBJECT_PERMANENCE,
        FailureClass.ACTION_OVERLOAD,
        FailureClass.SPATIAL_AXIS,
    ]
    assert d.character_refs_first and not d.allow_composites
    assert d.lock_screen_positions and d.lock_camera_static
    assert d.emphasize_objects == ["Brass Compass"]
    assert not d.drop_first_frame and not d.escalated
    assert {"character_design_matches_refs", "objects_persist_whole_take"} <= set(
        d.constraint_tokens
    )
    assert d.must_achieve and not any(BANNED_RE.search(t) for t in d.must_achieve)


def test_start_frame_flag_only_drops_first_frame(default_cfg: Config) -> None:
    report = QAReport(passed=False, artifact_flags=["start_frame_bleed"])
    d = diagnose_failure(report, _CTX, default_cfg.qa, attempt=1)
    assert d.failure_classes == [FailureClass.START_FRAME]
    assert d.drop_first_frame and not d.lock_camera_static and d.allow_composites


def test_attempt_two_escalates_and_compiles_stabilised_spec(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    report = QAReport(passed=False, artifact_flags=["style_drift"])
    d = diagnose_failure(report, _CTX, default_cfg.qa, attempt=2)
    assert d.escalated and d.attempt == 2 and d.drop_first_frame
    assert d.refs_characters_and_props_only and not d.allow_composites
    assert (
        d.min_desc_level >= 2 and "single_consistent_art_style" in d.constraint_tokens
    )

    view = shot_view(tmp_repo, "shot_1")
    plan = select_references(view, default_cfg, repo=tmp_repo, repair=d)
    assert all("loc_cafe" not in a.depicts_entity_ids for a in plan.selected_assets)
    assert plan.first_frame is None
    pkg = compile_shot(view, plan, default_cfg, repair=d)
    spec = json.loads(pkg.compiled_prompt)
    assert spec["camera"]["move"] == "static"
    assert {"camera_locked_static", "single_consistent_art_style"} <= set(
        spec["constraints"]
    )
    assert spec["sequence"], "story sequence must never be trimmed by a repair"


def test_repair_loop_stops_at_first_qa_pass(
    tmp_repo: Repo, default_cfg: Config, qa_script: dict[str, list[bool]]
) -> None:
    seed_valid_graph(tmp_repo)
    qa_script["shot_1"] = [False, True, False]
    video = _video(default_cfg)
    report = repair_failed_shots(tmp_repo, default_cfg, video, MockVLMProvider())
    (outcome,) = report.outcomes
    assert outcome.outcome == "approved" and outcome.renders == 2
    assert len(video.calls) == 2 and _shot(tmp_repo).repair_attempts == 1
    assert "constraints" in video.calls[1].compiled_prompt
    assert "screen_positions_locked" in video.calls[1].compiled_prompt
    assert video.calls[0].seed != video.calls[1].seed
    assert evaluate_shot_readiness(tmp_repo).is_complete


def test_two_failed_repairs_flag_shot_without_third_attempt(
    tmp_repo: Repo, default_cfg: Config, qa_script: dict[str, list[bool]]
) -> None:
    seed_valid_graph(tmp_repo)
    qa_script["shot_1"] = [False] * 10
    video = _video(default_cfg)
    report = repair_failed_shots(tmp_repo, default_cfg, video, MockVLMProvider())
    assert (
        report.flagged == ["shot_1"] and len(video.calls) == 3
    )  # 1 render + 2 repairs
    shot = _shot(tmp_repo)
    assert shot.needs_manual_edit and shot.repair_attempts == 2
    assert "object vanished" in shot.manual_edit_reasons
    blocking = evaluate_shot_readiness(tmp_repo).blocking[0]
    assert blocking.needs_manual_edit and blocking.clip_omni_prompt

    repair_failed_shots(tmp_repo, default_cfg, video, MockVLMProvider())
    tmp_repo.put_shot(shot.model_copy(update={"needs_manual_edit": False}))
    again = repair_failed_shots(tmp_repo, default_cfg, video, MockVLMProvider())
    assert len(video.calls) == 3, "budget exhausted: no further renders"
    assert again.flagged == ["shot_1"] and _shot(tmp_repo).needs_manual_edit


def test_s8_runs_repairs_after_initial_attempts_then_flags(
    tmp_repo: Repo, default_cfg: Config, qa_script: dict[str, list[bool]]
) -> None:
    seed_valid_graph(tmp_repo)
    qa_script["shot_1"] = [False] * 10
    video, vlm = _video(default_cfg), MockVLMProvider()
    render_single_shot_with_qa(
        tmp_repo, default_cfg, video, vlm, {}, _shot(tmp_repo), 1
    )
    assert len(video.calls) == 3 and _shot(tmp_repo).needs_manual_edit
    crs = tmp_repo.list_change_requests()
    assert crs and crs[-1].proposed_patch["action"] == "manual_edit"
    render_single_shot_with_qa(
        tmp_repo, default_cfg, video, vlm, {}, _shot(tmp_repo), 1
    )
    assert len(video.calls) == 3, "flagged shots are skipped by S8"


def test_s8_repair_success_clears_without_flag(
    tmp_repo: Repo, default_cfg: Config, qa_script: dict[str, list[bool]]
) -> None:
    seed_valid_graph(tmp_repo)
    qa_script["shot_1"] = [False, False, True]
    video = _video(default_cfg)
    shot = _shot(tmp_repo)
    render_single_shot_with_qa(
        tmp_repo, default_cfg, video, MockVLMProvider(), {}, shot, 1
    )
    after = _shot(tmp_repo)
    assert len(video.calls) == 3 and after.repair_attempts == 2
    assert not after.needs_manual_edit and evaluate_shot_readiness(tmp_repo).is_complete


def test_clip_edit_resets_flags_and_marks_stale(tmp_repo: Repo) -> None:
    seed_valid_graph(tmp_repo)
    flagged = _shot(tmp_repo).model_copy(
        update={
            "content_hash": "h_old",
            "needs_manual_edit": True,
            "repair_attempts": 2,
            "manual_edit_reasons": ["object vanished"],
        }
    )
    tmp_repo.put_shot(flagged)
    with pytest.raises(ValidationFailed):
        edit_shot_clip(tmp_repo, "shot_1", ClipEdit(step_actions={99: "x"}))
    with pytest.raises(ValidationFailed):
        edit_shot_clip(tmp_repo, "shot_1", ClipEdit(omni_prompt="   "))
    assert _shot(tmp_repo).needs_manual_edit, "rejected edits leave state untouched"

    prompt = 'Arjun holds the brass compass up. Arjun says: "The compass points north."'
    saved = edit_shot_clip(tmp_repo, "shot_1", ClipEdit(omni_prompt=prompt))
    assert saved.stale and saved.content_hash != "h_old"
    assert not saved.needs_manual_edit and saved.repair_attempts == 0
    assert saved.manual_edit_reasons == []
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None and scene.clips[0].omni_prompt == prompt


def _seed_continuity_scene(repo: Repo) -> None:
    base = seed_valid_graph(repo)
    steps = [
        InteractionStep(step_index=i, actor_id="char_arjun", action=f"Arjun step {i}")
        for i in (1, 2, 3)
    ]
    set_scene_clips(repo, "scn_1", [[1], [2], [3]], steps=steps)
    for idx in (2, 3):
        repo.put_shot(
            base.model_copy(
                update={
                    "id": f"shot_{idx}",
                    "index_in_scene": idx,
                    "clip_index": idx,
                    "story_order": 15 + idx,
                    "dialogue_ids": [],
                    "continue_from_last_frame": True,
                }
            )
        )


def test_continuity_followers_rerender_after_predecessor_repaired(
    tmp_repo: Repo, default_cfg: Config, qa_script: dict[str, list[bool]]
) -> None:
    _seed_continuity_scene(tmp_repo)
    vlm = MockVLMProvider()
    repair_failed_shots(tmp_repo, default_cfg, _video(default_cfg), vlm)
    assert evaluate_shot_readiness(tmp_repo).is_complete

    qa_script["shot_1"] = [False, True]
    video = _video(default_cfg)
    report = regenerate_shot(tmp_repo, default_cfg, video, vlm, "shot_1")
    got = [(o.shot_id, o.outcome, o.continuity_follower_of) for o in report.outcomes]
    assert got == [
        ("shot_1", "approved", None),
        ("shot_2", "approved", "shot_1"),
        ("shot_3", "approved", "shot_2"),
    ]
    assert [c.shot_id for c in video.calls] == ["shot_1", "shot_1", "shot_2", "shot_3"]
    assert not any(s.stale for s in tmp_repo.list_shots())


def test_forced_s8_still_clears_runs_and_resets_repair_state(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    from services.productions_service import _execute_requested_stage

    pipe = Pipeline(
        repo=tmp_repo,
        cfg=default_cfg,
        image_gen=MockImageGenerator(),
        video_gen=_video(default_cfg),
        vlm=MockVLMProvider(),
    )
    story = "Detective Arjun enters the rain-lit cafe carrying a brass compass."
    pipe.run_until_gate_or_done(story_text=story, auto_approve_gates=True)
    old_runs = {r.id for r in tmp_repo.list_generation_runs()}
    first = tmp_repo.list_shots()[0]
    tmp_repo.put_shot(
        first.model_copy(update={"needs_manual_edit": True, "repair_attempts": 2})
    )
    _execute_requested_stage(pipe, Stage.S8_RENDER, True)
    assert old_runs and not old_runs & {r.id for r in tmp_repo.list_generation_runs()}
    after = _shot(tmp_repo, first.id)
    assert not after.needs_manual_edit and after.repair_attempts == 0
