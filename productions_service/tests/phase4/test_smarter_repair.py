"""Phase 4 smarter repair: spec-vs-render routing, clip spec regeneration, follower candidates."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from conftest import seed_valid_graph, set_scene_clips

from storygraph.adapters.mock import MockVideoGenerator, MockVLMProvider
from storygraph.agents.role import clip_respec
from storygraph.agents.role.clip_respec import ClipRespecOutput
from storygraph.agents.runner import RoleRunResult
from storygraph.assembly import evaluate_shot_readiness
from storygraph.config import Config
from storygraph.pipeline import repair_route, shot_attempt
from storygraph.repair import classify_route
from storygraph.repair.loop import regenerate_shot, repair_failed_shots
from storygraph.repo import Repo
from storygraph.schema import (
    GenerationRun,
    InteractionStep,
    QADefect,
    QAReport,
    Shot,
    Status,
)
from storygraph.shots import compute_shot_content_hash, find_scene_clip

_NEW_PROMPT = "Arjun lifts the brass compass and studies it in silence."


def _spec_fail() -> QAReport:
    """A failure the critic attributes to the spec (structured `likely_cause='spec'`)."""
    return QAReport(
        passed=False,
        object_permanence=0.4,
        artifact_flags=["object_materialized"],
        failure_reasons=["the compass appears although the spec has it pocketed"],
        defects=[
            QADefect(
                type="object_state",
                severity="high",
                subject="Brass Compass",
                evidence="spec start state contradicts the scripted action",
                likely_cause="spec",
            )
        ],
    )


def _render_fail() -> QAReport:
    return QAReport(
        passed=False, artifact_flags=["style_drift"], suggested_fix="retry_seed"
    )


@pytest.fixture()
def qa_script(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, list[QAReport | None]]]:
    """Per-shot scripted critic verdicts (None = pass); unscripted renders pass."""
    script: dict[str, list[QAReport | None]] = {}

    def _critic(
        repo: Repo, cfg: Config, vlm: object, shot: Shot, run: GenerationRun
    ) -> QAReport:
        seq = script.get(shot.id, [])
        verdict = (seq.pop(0) if seq else None) or QAReport()
        status = Status.APPROVED if verdict.passed else Status.FAILED
        repo.update_generation_run_qa(run_id=run.id, qa_scores=verdict, status=status)
        return verdict

    monkeypatch.setattr(shot_attempt, "evaluate_clip_qa", _critic)
    yield script


@pytest.fixture()
def respec_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Screenwriter returns a rewritten clip prompt; records each clip-respec call."""
    calls: list[str] = []

    def _role(**kwargs: Any) -> RoleRunResult:
        calls.append(str(kwargs["role"]))
        return RoleRunResult(
            output=ClipRespecOutput(omni_prompt=f"{_NEW_PROMPT} v{len(calls)}")
        )

    monkeypatch.setattr(clip_respec, "run_role", _role)
    return calls


def _hashed_graph(repo: Repo) -> Shot:
    """Seed the valid graph with a real content hash on shot_1 (as the director writes it)."""
    shot = seed_valid_graph(repo)
    scene = repo.get_scene(shot.scene_id)
    clip = find_scene_clip(scene.clips, shot.clip_index) if scene else None
    return repo.put_shot(
        shot.model_copy(update={"content_hash": compute_shot_content_hash(shot, clip)})
    )


def _video(cfg: Config) -> MockVideoGenerator:
    return MockVideoGenerator(caps=cfg.video)


def test_spec_caused_failure_regenerates_clip_spec_instead_of_reseeding(
    tmp_repo: Repo,
    default_cfg: Config,
    qa_script: dict[str, list[QAReport | None]],
    respec_calls: list[str],
) -> None:
    before = _hashed_graph(tmp_repo)
    qa_script["shot_1"] = [_spec_fail(), None]
    video = _video(default_cfg)
    report = repair_failed_shots(tmp_repo, default_cfg, video, MockVLMProvider())
    (outcome,) = report.outcomes
    assert outcome.outcome == "approved" and outcome.routes == ["spec"]
    assert report.to_payload()["outcomes"][0]["routes"] == ["spec"]  # type: ignore[index]
    assert len(respec_calls) == 1 and len(video.calls) == 2
    repaired = video.calls[1].compiled_prompt
    assert _NEW_PROMPT in repaired, "render used the regenerated clip spec"
    assert "objects_persist_whole_take" not in repaired, (
        "no render directive on spec route"
    )
    shot = tmp_repo.get_shot("shot_1")
    assert shot is not None and shot.content_hash != before.content_hash
    assert shot.repair_attempts == 1, "spec regeneration is charged as a repair attempt"
    assert evaluate_shot_readiness(tmp_repo).is_complete


def test_render_caused_failure_keeps_directive_route(
    tmp_repo: Repo,
    default_cfg: Config,
    qa_script: dict[str, list[QAReport | None]],
    respec_calls: list[str],
) -> None:
    _hashed_graph(tmp_repo)
    qa_script["shot_1"] = [_render_fail(), None]
    video = _video(default_cfg)
    (outcome,) = repair_failed_shots(
        tmp_repo, default_cfg, video, MockVLMProvider()
    ).outcomes
    assert outcome.routes == ["render"] and not respec_calls
    assert "single_consistent_art_style" in video.calls[1].compiled_prompt


def test_spec_route_respects_two_repair_cap_then_flags(
    tmp_repo: Repo,
    default_cfg: Config,
    qa_script: dict[str, list[QAReport | None]],
    respec_calls: list[str],
) -> None:
    _hashed_graph(tmp_repo)
    qa_script["shot_1"] = [_spec_fail() for _ in range(10)]
    video = _video(default_cfg)
    (outcome,) = repair_failed_shots(
        tmp_repo, default_cfg, video, MockVLMProvider()
    ).outcomes
    assert outcome.outcome == "flagged" and outcome.routes == ["spec", "spec"]
    assert len(video.calls) == 3 and len(respec_calls) == 2  # 1 render + 2 repairs
    shot = tmp_repo.get_shot("shot_1")
    assert shot is not None and shot.repair_attempts == 2 and shot.needs_manual_edit
    again = repair_failed_shots(tmp_repo, default_cfg, video, MockVLMProvider())
    assert not again.outcomes and len(video.calls) == 3, "flagged: no further renders"


def test_route_precedence_lint_defects_repeat_and_reasons(
    default_cfg: Config,
) -> None:
    qa = default_cfg.qa
    first, again = _render_fail(), _render_fail()
    assert classify_route(first, [], [], qa).route == "render"
    assert classify_route(again, [first], [], qa).route == "spec", "repeat => spec"
    render_defect = {"likely_cause": "render"}
    pointing = first.model_copy(update={"suggested_fix": "recompile_prompt"})
    assert classify_route(pointing, [], [], qa).route == "spec"
    with_render_defect = pointing.model_copy(update={"defects": [render_defect]})
    assert classify_route(with_render_defect, [], [], qa).route == "render", (
        "structured render cause beats free-text heuristics"
    )
    spec_defects = first.model_copy(
        update={
            "defects": [
                {"likely_cause": "spec"},
                {"likely_cause": "spec"},
                {"likely_cause": "reference"},
            ]
        }
    )
    assert classify_route(spec_defects, [], [], qa).route == "spec"
    tie = first.model_copy(
        update={"defects": [{"likely_cause": "spec"}, {"likely_cause": "reference"}]}
    )
    assert classify_route(tie, [], [], qa).route == "render"
    lint = ["sequence mentions undeclared prop"]
    assert classify_route(first, [], lint, qa).route == "spec"


def test_blocking_lint_issues_feed_route_and_linter_errors_are_ignored(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    from storygraph.pipeline.shot_attempt import RenderDeps

    deps = RenderDeps(tmp_repo, default_cfg, _video(default_cfg), MockVLMProvider())
    issues = [
        type("I", (), {"severity": "warning", "message": "minor"})(),
        type("I", (), {"severity": "error", "message": "prop out of lifetime"})(),
    ]
    monkeypatch.setattr(repair_route, "_load_linter", lambda: lambda *_: issues)
    assert repair_route.lint_blocking_issues(deps, "shot_1") == ["prop out of lifetime"]

    def _boom(*_: object) -> object:
        raise RuntimeError("linter crashed")

    monkeypatch.setattr(repair_route, "_load_linter", lambda: _boom)
    assert repair_route.lint_blocking_issues(deps, "shot_1") == []


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


def _winners(repo: Repo) -> dict[str, str]:
    return {r.shot_id: r.run_id for r in evaluate_shot_readiness(repo).ready_shots}


def test_follower_candidate_failure_keeps_old_approved_clip(
    tmp_repo: Repo, default_cfg: Config, qa_script: dict[str, list[QAReport | None]]
) -> None:
    _seed_continuity_scene(tmp_repo)
    vlm = MockVLMProvider()
    repair_failed_shots(tmp_repo, default_cfg, _video(default_cfg), vlm)
    old = _winners(tmp_repo)
    qa_script["shot_2"] = [_render_fail()]
    video = _video(default_cfg)
    report = regenerate_shot(tmp_repo, default_cfg, video, vlm, "shot_1")
    got = [(o.shot_id, o.outcome, o.candidate) for o in report.outcomes]
    assert got == [("shot_1", "approved", None), ("shot_2", "approved", "rejected")]
    assert [c.shot_id for c in video.calls] == ["shot_1", "shot_2"], (
        "no repairs on a candidate"
    )
    readiness = evaluate_shot_readiness(tmp_repo)
    assert readiness.is_complete and _winners(tmp_repo)["shot_2"] == old["shot_2"]
    follower = tmp_repo.get_shot("shot_2")
    assert (
        follower is not None and not follower.needs_manual_edit and not follower.stale
    )
    assert follower.repair_attempts == 0


def test_follower_candidate_pass_replaces_approved_clip(
    tmp_repo: Repo, default_cfg: Config, qa_script: dict[str, list[QAReport | None]]
) -> None:
    _seed_continuity_scene(tmp_repo)
    vlm = MockVLMProvider()
    repair_failed_shots(tmp_repo, default_cfg, _video(default_cfg), vlm)
    old = _winners(tmp_repo)
    report = regenerate_shot(tmp_repo, default_cfg, _video(default_cfg), vlm, "shot_1")
    assert [o.candidate for o in report.outcomes] == [None, "accepted", "accepted"]
    new = _winners(tmp_repo)
    assert evaluate_shot_readiness(tmp_repo).is_complete
    assert new["shot_2"] != old["shot_2"] and new["shot_3"] != old["shot_3"]
