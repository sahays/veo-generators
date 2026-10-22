"""S7 lint stage: deterministic remediation first, scene-scoped LLM redo with feedback after."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase1"))
from kitchen_seed import seed_kitchen

from storygraph.adapters.mock import MockVideoGenerator
from storygraph.config import Config
from storygraph.pipeline import lint_stage
from storygraph.pipeline.lint_stage import LintStageDeps, compile_and_lint
from storygraph.repo import Repo
from storygraph.schema import CameraSpec
from storygraph.state import rebuild_state_facts


def _deps(repo: Repo, cfg: Config) -> LintStageDeps:
    return LintStageDeps(
        repo=repo, cfg=cfg, video_gen=MockVideoGenerator(caps=cfg.video)
    )


def _set_camera(repo: Repo, shot_id: str, cam: CameraSpec) -> None:
    shot = repo.get_shot(shot_id)
    assert shot is not None
    repo.put_shot(shot.model_copy(update={"camera": cam}))


def _edit_step(repo: Repo, index: int, **update: str) -> None:
    scene = repo.get_scene("scn_4")
    assert scene is not None
    steps = [
        s.model_copy(update=update) if s.step_index == index else s
        for s in scene.interaction_steps
    ]
    repo.put_scene(scene.model_copy(update={"interaction_steps": steps}))
    rebuild_state_facts(repo)


def _no_llm(*_args: object, **_kwargs: object) -> list[str]:
    raise AssertionError("deterministic remediation must not call the LLM redo")


def test_bad_locomotion_camera_is_fixed_without_llm_and_recorded(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_kitchen(tmp_repo)  # clip 2: "marches to the table …" (locomotion)
    _set_camera(
        tmp_repo,
        "shot_4_2",
        CameraSpec(shot_size="ECU", angle="low", movement="static", lens_mm=85),
    )
    monkeypatch.setattr(lint_stage, "llm_redo", _no_llm)
    packages = compile_and_lint(_deps(tmp_repo, default_cfg))
    shot = tmp_repo.get_shot("shot_4_2")
    assert shot is not None and {"shot_4_1", "shot_4_2"} <= set(packages)
    assert (shot.camera.shot_size, shot.camera.movement) == ("MS", "track")
    assert (shot.camera.angle, shot.camera.lens_mm) == ("low", 85)
    assert [(r.code, r.status) for r in shot.lint_issues] == [
        ("S4_LINT_CAMERA_MOVEMENT", "auto_fixed")
    ]
    assert (
        shot.stale and shot.content_hash
    )  # render content changed → old clips invalid


def test_overloaded_clip_is_split_and_shots_remapped(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_kitchen(tmp_repo)
    _edit_step(tmp_repo, 3, action="grabs the kitchen towel", target_id="obj_towel")
    wide = CameraSpec(shot_size="WS", movement="track", lens_mm=24)
    _set_camera(tmp_repo, "shot_4_2", wide)
    monkeypatch.setattr(lint_stage, "llm_redo", _no_llm)
    compile_and_lint(_deps(tmp_repo, default_cfg))
    scene = tmp_repo.get_scene("scn_4")
    assert scene is not None
    assert [c.step_indices for c in scene.clips] == [[1, 2], [3], [4, 5, 6]]
    shots = sorted(
        tmp_repo.list_shots(scene_id="scn_4"), key=lambda s: s.index_in_scene
    )
    assert [s.clip_index for s in shots] == [1, 2, 3]
    assert [s.duration_s for s in shots] == [c.duration_s for c in scene.clips]
    assert shots[2].camera.model_dump(exclude={"focus_target_id"}) == wide.model_dump(
        exclude={"focus_target_id"}
    )
    assert ("S2_CLIP_LINT_TOO_MANY_ACTIONS", "auto_fixed") in {
        (r.code, r.status) for r in shots[0].lint_issues
    }


@dataclass
class _Calls:
    screenwriter: list[tuple[str, list[str]]] = field(default_factory=list)
    director: list[tuple[str, list[str]]] = field(default_factory=list)


def test_unfixable_issue_reauthors_only_its_scene_with_feedback_then_demotes(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_kitchen(tmp_repo)
    _edit_step(tmp_repo, 4, target_id="prop_chair")  # raw id: S2 must rewrite it
    calls = _Calls()

    def _sw(
        _ctx: object, scene_id: str, _lang: str, _llm: object, fb: list[str]
    ) -> None:
        calls.screenwriter.append((scene_id, list(fb)))

    def _dr(_ctx: object, scene_id: str, _llm: object, fb: list[str]) -> None:
        calls.director.append((scene_id, list(fb)))

    monkeypatch.setattr(lint_stage, "run_screenwriter_for_scene", _sw)
    monkeypatch.setattr(lint_stage, "run_director_for_scene", _dr)
    packages = compile_and_lint(_deps(tmp_repo, default_cfg))
    assert "shot_4_2" in packages  # no dead end: the renderable shot still compiles
    assert [s for s, _ in calls.screenwriter] == ["scn_4", "scn_4"]
    assert len(calls.director) == 2
    assert all(
        any(m.startswith("clip 2: step 1 targets unknown entity") for m in fb)
        for _, fb in calls.screenwriter
    )
    shot = tmp_repo.get_shot("shot_4_2")
    assert shot is not None
    assert ("S2_CLIP_LINT_UNKNOWN_TARGET", "demoted", "warn") in {
        (r.code, r.status, r.severity) for r in shot.lint_issues
    }
