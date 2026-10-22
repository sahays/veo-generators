"""S6 never dead-ends: species → scene rewrite; leftovers demoted; only unrenderable blocks."""

from __future__ import annotations

import pytest
from storygraph.config import Config
from storygraph.errors import ValidationFailed
from storygraph.pipeline import validate_stage
from storygraph.pipeline.validate_stage import ValidateStageDeps, review_and_redo
from storygraph.repo import Repo
from storygraph.schema import Entity
from two_location_seed import HELPER, seed_two_locations


def _deps(repo: Repo, cfg: Config, redo: list[list[str]]) -> ValidateStageDeps:
    return ValidateStageDeps(repo=repo, cfg=cfg, redo_stages=redo.append)


def _set_scene(repo: Repo, scene_id: str, **update: object) -> None:
    scene = repo.get_scene(scene_id)
    assert scene is not None
    repo.put_scene(scene.model_copy(update=update))


def test_unfixable_issues_are_demoted_to_affected_shots_and_pipeline_continues(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_two_locations(tmp_repo)
    helper = tmp_repo.get_entity(HELPER)
    assert isinstance(helper, Entity)
    tmp_repo.put_entity(
        helper.model_copy(update={"aliases": ["Hero"]})
    )  # V12 duplicate
    shot = tmp_repo.get_shot("shot_2_2")
    assert shot is not None
    tmp_repo.put_shot(shot.model_copy(update={"duration_s": 0.0}))  # V6, auto-fixable
    out = review_and_redo(_deps(tmp_repo, default_cfg, []), max_iterations=1)
    assert any(f.startswith("shot_2_2:") for f in out.fixes)
    fixed = tmp_repo.get_shot("shot_2_2")
    assert (
        fixed is not None and 0 < fixed.duration_s <= default_cfg.video.max_duration_s
    )
    records = {(r.code, r.status, r.severity, r.source) for r in fixed.lint_issues}
    assert ("V12", "demoted", "warn", "S6") in records
    reports = [
        d
        for d in tmp_repo.store.query("stage_qa_reports")
        if d["stage"] == "S6_VALIDATE"
    ]
    assert reports and reports[-1]["passed"] is True


def test_species_violation_rewrites_only_its_scene_with_the_rule_message(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_two_locations(tmp_repo)
    scene = tmp_repo.get_scene("scn_2")
    assert scene is not None
    bad = scene.clips[0].model_copy(
        update={"omni_prompt": "Hero drops low and barks at the stream."}
    )
    _set_scene(tmp_repo, "scn_2", clips=[bad, *scene.clips[1:]])
    calls: list[tuple[str, list[str]]] = []

    def _sw(_c: object, sid: str, _l: str, _m: object, fb: list[str]) -> None:
        calls.append((sid, list(fb)))

    monkeypatch.setattr(validate_stage, "run_screenwriter_for_scene", _sw)
    monkeypatch.setattr(validate_stage, "run_director_for_scene", lambda *_a: None)
    redo: list[list[str]] = []
    out = review_and_redo(_deps(tmp_repo, default_cfg, redo), max_iterations=2)
    assert [sid for sid, _ in calls] == ["scn_2"]
    assert "Hero (person) cannot 'barks' literally" in calls[0][1][0]
    assert all("S2_SCREENPLAY" not in stages for stages in redo)  # no whole-stage redo
    assert any(
        i.code == "S2_CLIP_SPECIES_ACTION" for i in out.demoted
    )  # stub fixed nothing


def test_unrenderable_shot_blocks_and_names_shot_and_reason(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_two_locations(tmp_repo)
    _set_scene(tmp_repo, "scn_2", location_id="loc_void")
    for sid in ("shot_2_1", "shot_2_2"):
        shot = tmp_repo.get_shot(sid)
        assert shot is not None
        tmp_repo.put_shot(shot.model_copy(update={"location_id": "loc_void"}))
    with pytest.raises(
        ValidationFailed,
        match=r"U_NO_LOCATION shot_2_1: .*location 'loc_void' is missing",
    ):
        review_and_redo(_deps(tmp_repo, default_cfg, []), max_iterations=1)
