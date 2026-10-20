"""Shot content-hash invalidation: regenerated shots must never reuse clips from older content."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import seed_valid_graph
from storygraph.adapters.mock import (
    MockImageGenerator,
    MockVideoGenerator,
    MockVLMProvider,
)
from storygraph.agents.role import screenwriter as screenwriter_mod
from storygraph.assembly import evaluate_shot_readiness
from storygraph.clips.models import ClipScript
from storygraph.config import Config
from storygraph.pipeline import Pipeline, Stage
from storygraph.pipeline.render_stage import (
    _is_shot_already_valid,
    render_single_shot_with_qa,
)
from storygraph.repo import Repo
from storygraph.schema import ActionBeat, GenerationRun, Role, Shot, Status
from storygraph.tools import write_tools as wt
from storygraph.tools.registry import ToolContext

_STORY = (
    "Detective Arjun enters the rain-lit corner cafe in a trenchcoat carrying a brass compass. "
    "He meets Dr. Meera at the table. Later, Arjun steps onto the monsoon skyline rooftop."
)


def _director_put(ctx: ToolContext, base: Shot, **overrides: Any) -> Shot:
    """Re-author `base` through the DIRECTOR `put_shot` write tool (as S4 does)."""
    fields: dict[str, Any] = {
        "shot_id": base.id,
        "scene_id": base.scene_id,
        "index_in_scene": base.index_in_scene,
        "story_order": base.story_order,
        "duration_s": base.duration_s,
        "location_id": base.location_id,
        "covers_event_ids": base.covers_event_ids,
        "cast": base.cast,
        "prop_ids": base.prop_ids,
        "camera": base.camera,
        "beats": base.beats,
        "dialogue_ids": base.dialogue_ids,
        "continue_from_last_frame": base.continue_from_last_frame,
        "look": base.look,
        "clip_index": base.clip_index,
    }
    fields.update(overrides)
    return Shot.model_validate(wt.put_shot(ctx, **fields))


def _render(repo: Repo, cfg: Config, video_gen: MockVideoGenerator) -> None:
    shot = repo.get_shot("shot_1")
    assert shot is not None
    render_single_shot_with_qa(repo, cfg, video_gen, MockVLMProvider(), {}, shot, 2)


@pytest.fixture()
def rendered(tmp_repo: Repo, default_cfg: Config) -> tuple[ToolContext, Shot]:
    """Seeded graph whose `shot_1` was authored by the director and rendered+approved once."""
    base = seed_valid_graph(tmp_repo)
    ctx = ToolContext(repo=tmp_repo, role=Role.DIRECTOR, cfg=default_cfg)
    authored = _director_put(ctx, base)
    _render(tmp_repo, default_cfg, MockVideoGenerator(caps=default_cfg.video))
    runs = tmp_repo.list_generation_runs(shot_id="shot_1")
    assert runs[-1].status == Status.APPROVED
    assert runs[-1].shot_content_hash == authored.content_hash is not None
    shot = tmp_repo.get_shot("shot_1")
    assert shot is not None and not shot.stale
    return ctx, shot


def test_changed_content_marks_stale_and_s8_rerenders(
    tmp_repo: Repo, default_cfg: Config, rendered: tuple[ToolContext, Shot]
) -> None:
    ctx, shot = rendered
    old_runs = {r.id for r in tmp_repo.list_generation_runs(shot_id=shot.id)}
    new_beat = ActionBeat(t_start_s=0.0, t_end_s=8.0, description="Arjun pockets it.")
    changed = _director_put(ctx, shot, beats=[new_beat])
    assert changed.content_hash != shot.content_hash
    assert changed.stale and changed.stale_reason == (
        "Shot content changed by director regeneration"
    )

    video_gen = MockVideoGenerator(caps=default_cfg.video)
    _render(tmp_repo, default_cfg, video_gen)
    assert len(video_gen.calls) == 1
    new_runs = [
        r
        for r in tmp_repo.list_generation_runs(shot_id=shot.id)
        if r.id not in old_runs
    ]
    assert new_runs and new_runs[-1].shot_content_hash == changed.content_hash
    after = tmp_repo.get_shot(shot.id)
    assert after is not None and not after.stale
    ready = evaluate_shot_readiness(tmp_repo).ready_shots
    assert [r.run_id for r in ready] == [new_runs[-1].id]


def test_unchanged_content_keeps_approved_run_and_skips_render(
    tmp_repo: Repo, default_cfg: Config, rendered: tuple[ToolContext, Shot]
) -> None:
    ctx, shot = rendered
    same = _director_put(ctx, shot)
    assert same.content_hash == shot.content_hash and not same.stale
    video_gen = MockVideoGenerator(caps=default_cfg.video)
    _render(tmp_repo, default_cfg, video_gen)
    assert video_gen.calls == []


def test_unchanged_content_preserves_upstream_staleness(
    tmp_repo: Repo, rendered: tuple[ToolContext, Shot]
) -> None:
    ctx, shot = rendered
    tmp_repo.put_shot(shot.model_copy(update={"stale": True, "stale_reason": "asset"}))
    same = _director_put(ctx, shot)
    assert same.stale and same.stale_reason == "asset"


def _add_approved_run(repo: Repo, run_id: str, attempt: int, h: str | None) -> None:
    uri = repo.blobs.put_bytes(f"clips/{run_id}.mp4", run_id.encode(), "video/mp4")
    repo.add_generation_run(
        GenerationRun(
            id=run_id,
            created_by=Role.PIPELINE,
            status=Status.APPROVED,
            shot_id="shot_1",
            attempt=attempt,
            provider="mock",
            model="mock",
            compiled_prompt="p",
            seed=1,
            package_hash="h",
            output_video_uri=uri,
            shot_content_hash=h,
        )
    )


def _set_shot(repo: Repo, **update: Any) -> Shot:
    shot = repo.get_shot("shot_1")
    assert shot is not None
    return repo.put_shot(shot.model_copy(update=update))


def test_readiness_blocks_approved_run_from_older_content(tmp_repo: Repo) -> None:
    seed_valid_graph(tmp_repo)
    _set_shot(tmp_repo, content_hash="h_new")
    _add_approved_run(tmp_repo, "run_old", 1, "h_old")
    readiness = evaluate_shot_readiness(tmp_repo)
    assert not readiness.ready_shots and not readiness.is_complete
    (block,) = readiness.blocking
    assert block.latest_status == "outdated"
    assert any("older screenplay/shot version" in r for r in block.failure_reasons)

    _add_approved_run(tmp_repo, "run_new", 2, "h_new")
    _add_approved_run(tmp_repo, "run_newer_but_old", 3, "h_old")
    ready = evaluate_shot_readiness(tmp_repo).ready_shots
    assert [r.run_id for r in ready] == ["run_new"]


def test_readiness_blocks_stale_shot_even_with_matching_run(tmp_repo: Repo) -> None:
    seed_valid_graph(tmp_repo)
    _set_shot(tmp_repo, content_hash="h", stale=True, stale_reason="asset changed")
    _add_approved_run(tmp_repo, "run_1", 1, "h")
    readiness = evaluate_shot_readiness(tmp_repo)
    assert not readiness.ready_shots
    assert "shot is stale: asset changed" in readiness.blocking[0].failure_reasons


@pytest.mark.parametrize(
    ("shot_hash", "run_hash", "counts"),
    [(None, None, True), ("h", None, False), (None, "h", False), ("h", "h", True)],
)
def test_legacy_hash_rule(
    tmp_repo: Repo,
    default_cfg: Config,
    shot_hash: str | None,
    run_hash: str | None,
    counts: bool,
) -> None:
    seed_valid_graph(tmp_repo)
    shot = _set_shot(tmp_repo, content_hash=shot_hash)
    _add_approved_run(tmp_repo, "run_1", 1, run_hash)
    runs = tmp_repo.list_generation_runs(shot_id="shot_1")
    vlm = MockVLMProvider()
    assert _is_shot_already_valid(tmp_repo, default_cfg, vlm, shot, runs) is counts
    assert evaluate_shot_readiness(tmp_repo).is_complete is counts


def _revise_clips(*args: Any, **kwargs: Any) -> list[ClipScript]:
    """Wrap `finalize_clips` so a re-run screenplay yields different clip prompts."""
    clips: list[ClipScript] = _ORIGINAL_FINALIZE(*args, **kwargs)
    return [
        c.model_copy(update={"omni_prompt": f"Revised. {c.omni_prompt}"}) for c in clips
    ]


_ORIGINAL_FINALIZE = screenwriter_mod.finalize_clips


def test_rerun_screenplay_then_downstream_never_assembles_old_clips(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.productions_service import _execute_requested_stage

    pipe = Pipeline(
        repo=tmp_repo,
        cfg=default_cfg,
        image_gen=MockImageGenerator(),
        video_gen=MockVideoGenerator(caps=default_cfg.video),
        vlm=MockVLMProvider(),
    )
    pipe.run_until_gate_or_done(story_text=_STORY, auto_approve_gates=True)
    old_run_ids = {r.id for r in tmp_repo.list_generation_runs()}
    assert evaluate_shot_readiness(tmp_repo).is_complete

    monkeypatch.setattr(screenwriter_mod, "finalize_clips", _revise_clips)
    _execute_requested_stage(pipe, Stage.S2_SCREENPLAY, True)
    downstream = [Stage.S4_SHOTS, Stage.S5_MUSIC, Stage.S6_VALIDATE, Stage.S7_COMPILE]
    for st in [*downstream, Stage.S8_RENDER, Stage.S9_QA, Stage.S10_ASSEMBLE]:
        _execute_requested_stage(pipe, st, False)

    readiness = evaluate_shot_readiness(tmp_repo)
    assert readiness.is_complete and readiness.ready_shots
    runs = {r.id: r for r in tmp_repo.list_generation_runs()}
    shots = {s.id: s for s in tmp_repo.list_shots()}
    for ready in readiness.ready_shots:
        assert ready.run_id not in old_run_ids
        assert runs[ready.run_id].shot_content_hash == shots[ready.shot_id].content_hash
    assert not any(s.stale for s in shots.values())
