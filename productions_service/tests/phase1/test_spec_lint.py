"""Phase 1: the blocking spec linter, its routing, and the S7 gate."""

from __future__ import annotations

import pytest
from kitchen_seed import MILO, PIP, seed_kitchen

from storygraph.agents.stage_qa import stages_to_redo_for_issues
from storygraph.config import Config
from storygraph.errors import ValidationFailed
from storygraph.lint.models import blocking
from storygraph.lint.spec_lint import lint_shot
from storygraph.pipeline import Pipeline, Stage
from storygraph.repo import Repo
from storygraph.schema import CameraSpec, DialogueLine, Role
from storygraph.state import rebuild_state_facts


def _codes(repo: Repo, cfg: Config, shot_id: str) -> set[str]:
    return {i.code for i in blocking(lint_shot(repo, cfg, shot_id))}


def _set_camera(repo: Repo, shot_id: str, cam: CameraSpec) -> None:
    shot = repo.get_shot(shot_id)
    assert shot is not None
    repo.put_shot(shot.model_copy(update={"camera": cam}))


def test_walk_with_static_close_up_is_blocked_but_tracking_passes(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_kitchen(tmp_repo)
    _set_camera(tmp_repo, "shot_4_2", CameraSpec(shot_size="CU", movement="static"))
    assert "S4_LINT_CAMERA_MOVEMENT" in _codes(tmp_repo, default_cfg, "shot_4_2")
    _set_camera(tmp_repo, "shot_4_2", CameraSpec(shot_size="MS", movement="track"))
    assert "S4_LINT_CAMERA_MOVEMENT" not in _codes(tmp_repo, default_cfg, "shot_4_2")


def test_overloaded_clip_and_long_speech_route_to_screenplay(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_kitchen(tmp_repo)
    tmp_repo.put_dialogue(
        DialogueLine(
            id="dlg_long", created_by=Role.SCREENWRITER, scene_id="scn_4", order_in_scene=1,
            speaker_id=PIP, text=" ".join(["word"] * 21),
        )
    )  # fmt: skip
    scene = tmp_repo.get_scene("scn_4")
    assert scene is not None
    steps = [
        s.model_copy(update={"action": "grabs the towel"}) if s.step_index == 6 else s
        for s in scene.interaction_steps
    ]
    tmp_repo.put_scene(scene.model_copy(update={"interaction_steps": steps}))
    shot = tmp_repo.get_shot("shot_4_2")
    assert shot is not None
    tmp_repo.put_shot(shot.model_copy(update={"dialogue_ids": ["dlg_long"]}))
    issues = blocking(lint_shot(tmp_repo, default_cfg, "shot_4_2"))
    codes = {i.code for i in issues}
    assert {"S2_CLIP_LINT_TOO_MANY_ACTIONS", "S2_CLIP_LINT_TOO_MANY_WORDS"} <= codes
    assert all(i.route == "S2" for i in issues if i.code.startswith("S2_"))
    assert stages_to_redo_for_issues([], list(issues), []) == [
        "S2_SCREENPLAY",
        "S4_SHOTS",
    ]
    assert "TOO_MANY_WORDS" in str(ValidationFailed(issues))


def test_raw_id_step_target_is_an_unknown_entity(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """Live scn_005: steps targeted `prop_towel`, which no entity owns."""
    seed_kitchen(tmp_repo)
    scene = tmp_repo.get_scene("scn_4")
    assert scene is not None
    steps = [
        s.model_copy(update={"target_id": "prop_chair"}) if s.step_index == 4 else s
        for s in scene.interaction_steps
    ]
    tmp_repo.put_scene(scene.model_copy(update={"interaction_steps": steps}))
    issues = lint_shot(tmp_repo, default_cfg, "shot_4_2")
    hit = next(i for i in issues if i.code == "S2_CLIP_LINT_UNKNOWN_TARGET")
    assert "prop_chair" not in hit.message and hit.node_id == "shot_4_2"


def test_moving_toward_an_already_adjacent_actor_is_a_contradiction(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_kitchen(tmp_repo)
    scene = tmp_repo.get_scene("scn_4")
    assert scene is not None
    ev = tmp_repo.get_event("evt_024")
    assert ev is not None
    effects = [
        *ev.effects,
        ev.effects[0].model_copy(
            update={
                "entity_id": PIP,
                "attribute": "sub_location",
                "new_value": "beside Milo",
            }
        ),
    ]
    tmp_repo.put_event(ev.model_copy(update={"effects": effects}))
    steps = [
        s.model_copy(update={"target_id": MILO, "action": "trots over to Milo"})
        if s.step_index == 6
        else s
        for s in scene.interaction_steps
    ]
    tmp_repo.put_scene(scene.model_copy(update={"interaction_steps": steps}))
    rebuild_state_facts(tmp_repo)
    assert "S2_CLIP_LINT_ALREADY_ADJACENT" in _codes(tmp_repo, default_cfg, "shot_4_2")


def test_s7_gate_reauthors_then_raises_without_compiling(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocking lint errors re-run the routed authoring stages, then fail S7 before S8."""
    seed_kitchen(tmp_repo)
    _set_camera(tmp_repo, "shot_4_2", CameraSpec(shot_size="ECU", movement="static"))
    pipe = Pipeline(tmp_repo, default_cfg)
    redone: list[str] = []

    def _record(st: Stage, _ihash: str, force: bool = False) -> None:
        redone.append(str(st))

    monkeypatch.setattr(pipe, "_execute_authoring_stage", _record)
    with pytest.raises(ValidationFailed, match="S4_LINT_CAMERA_MOVEMENT shot_4_2"):
        pipe._compile_and_lint(max_iterations=2)
    assert redone == ["S4_SHOTS"] and pipe.compiled_packages == {}
