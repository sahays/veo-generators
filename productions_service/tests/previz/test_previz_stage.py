"""S8_PREVIZ stage + promote + HTTP contract: reuse, failure isolation, run records, promotion."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import add_clip_shot, seed_valid_graph, set_scene_clips
from pydantic import ValidationError

from services.previz_contract import PrevizRunPayload, PromotePrevizPayload
from storygraph.errors import NotFound, ValidationFailed
from storygraph.keyframes.plan.models import KeyframePlan, PlanInput
from storygraph.previz.stage.deps import LayoutSource, PrevizStageDeps
from storygraph.previz.stage.promote import promote_variant
from storygraph.previz.stage.stage import run_previz
from storygraph.repo import Repo
from storygraph.repo.previz_shots import PrevizRunRepo, PrevizShotRepo
from storygraph.schema import InteractionStep, Role, Scene, Status
from storygraph.schemas.previz import PrevizLayout, PrevizRun, PrevizVariantRecord
from storygraph.schemas.previz_scene import (
    BlockingTrack,
    CameraRig,
    LocationLayout,
    PrevizScene,
    Vec3,
)


@dataclass
class FakeResult:
    ok: bool
    mp4_path: Path | None
    seconds: float = 1.5
    blender_version: str | None = "4.2.23"
    failure_text: str | None = None


class FakeRenderer:
    """Writes a tiny file as the MP4; fails for shots listed in `fail` (typed reason)."""

    def __init__(self, fail: frozenset[str] = frozenset()) -> None:
        self.fail, self.calls = fail, []

    def version(self) -> str | None:
        return "4.2.23"

    def render(self, scene: PrevizScene, workdir: Path) -> FakeResult:
        self.calls.append(scene.blocking.shot_id)
        if scene.blocking.shot_id in self.fail:
            return FakeResult(False, None, failure_text="nonzero_exit: Error: bad mesh")
        out = workdir / "out.mp4"
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42" + scene.blocking.shot_id.encode())
        return FakeResult(True, out)


def _layout(scene: Scene) -> PrevizLayout:
    return PrevizLayout(
        id="pzl_loc_1",
        created_by=Role.PIPELINE,
        location_id="loc",
        layout=LocationLayout(location_id="loc", name="Room"),
    )


def _build(
    inp: PlanInput, plan: KeyframePlan, layout: LocationLayout, scene: Scene
) -> PrevizScene:
    return PrevizScene(
        layout=layout,
        camera=CameraRig(position=Vec3(y=-5, z=1.6), target=Vec3(y=3, z=1)),
        blocking=BlockingTrack(
            shot_id=plan.shot_id, scene_id=plan.scene_id, clip_index=plan.clip_index,
            duration_s=plan.duration_s,
        ),
    )  # fmt: skip


def _two_clip_scene(repo: Repo) -> None:
    base = seed_valid_graph(repo)
    steps = [
        InteractionStep(step_index=1, actor_id="char_arjun", target_id="obj_compass",
                        action="Arjun lifts the brass compass", duration_hint_s=4.0),
        InteractionStep(step_index=2, actor_id="char_arjun", target_id="obj_compass",
                        action="Arjun sets the compass on the counter", duration_hint_s=4.0),
    ]  # fmt: skip
    set_scene_clips(repo, "scn_1", [[1], [2]], steps=steps)
    add_clip_shot(repo, base, "shot_2", 2, 20)


def _deps(
    repo: Repo, renderer: FakeRenderer, tmp: Path, layouts: LayoutSource = _layout
) -> PrevizStageDeps:
    return PrevizStageDeps(repo, renderer, layouts, _build, tmp)


_SEQ = itertools.count()


def _run(repo: Repo, variant: str = "previz_only", force: bool = False) -> PrevizRun:
    return PrevizRunRepo(repo.store).put(
        PrevizRun(id=f"pzr_{next(_SEQ)}", created_by=Role.HUMAN, variant=variant,  # type: ignore[arg-type]
                  force=force, started_at="2026-10-23T00:00:00+00:00")
    )  # fmt: skip


def test_previz_renders_each_clip_once_then_reuses(
    tmp_repo: Repo, tmp_path: Path
) -> None:
    _two_clip_scene(tmp_repo)
    renderer = FakeRenderer()
    final = run_previz(_deps(tmp_repo, renderer, tmp_path), _run(tmp_repo))
    assert (
        final.run_status == "approved" and final.shots_done == 2 and final.finished_at
    )
    shots = PrevizShotRepo(tmp_repo.store).active_by_shot()
    assert {s.previz_status for s in shots.values()} == {"done"}
    assert all(s.previz_video_uri and s.render_seconds == 1.5 for s in shots.values())
    rows = tmp_repo.list_stage_runs("S8_PREVIZ")
    assert sorted(r.completed for r in rows) == [False, True]  # start row + final row
    calls = len(renderer.calls)
    run_previz(_deps(tmp_repo, renderer, tmp_path), _run(tmp_repo, force=False))
    assert len(renderer.calls) == calls  # unchanged scenes -> no re-render
    run_previz(_deps(tmp_repo, renderer, tmp_path), _run(tmp_repo, force=True))
    assert len(renderer.calls) == calls + 2
    assert PrevizShotRepo(tmp_repo.store).active_for_shot("shot_1").version == 2  # type: ignore[union-attr]


def test_render_failure_is_recorded_and_other_clips_continue(
    tmp_repo: Repo, tmp_path: Path
) -> None:
    _two_clip_scene(tmp_repo)
    final = run_previz(
        _deps(tmp_repo, FakeRenderer(frozenset({"shot_1"})), tmp_path), _run(tmp_repo)
    )
    shots = PrevizShotRepo(tmp_repo.store).active_by_shot()
    assert shots["shot_1"].previz_status == "failed"
    assert shots["shot_1"].failure_reason == "nonzero_exit: Error: bad mesh"
    assert shots["shot_2"].previz_status == "done"
    assert final.run_status == "approved" and final.shots_failed == 1


def test_layout_failure_fails_scene_clips_with_reason_and_closes_run(
    tmp_repo: Repo, tmp_path: Path
) -> None:
    _two_clip_scene(tmp_repo)

    def broken(scene: Scene) -> PrevizLayout:
        raise ValueError("location sheet missing")

    final = run_previz(
        _deps(tmp_repo, FakeRenderer(), tmp_path, broken), _run(tmp_repo)
    )
    shots = PrevizShotRepo(tmp_repo.store).active_by_shot()
    assert {s.failure_reason for s in shots.values()} == {
        "ValueError: location sheet missing"
    }
    assert final.run_status == "failed" and "location sheet missing" in (
        final.error or ""
    )


def test_variants_without_adapters_fail_per_variant_not_per_run(
    tmp_repo: Repo, tmp_path: Path
) -> None:
    _two_clip_scene(tmp_repo)
    run_previz(_deps(tmp_repo, FakeRenderer(), tmp_path), _run(tmp_repo, "both"))
    ps = PrevizShotRepo(tmp_repo.store).active_for_shot("shot_1")
    assert ps is not None and ps.previz_status == "done"
    assert {(v.variant, v.status) for v in ps.variants} == {
        ("E1_omni_restyle", "failed"),
        ("E2_keyframe_restyle", "failed"),
    }


def test_promote_creates_next_attempt_run_and_marks_single_variant(
    tmp_repo: Repo, tmp_path: Path
) -> None:
    _two_clip_scene(tmp_repo)
    run_previz(_deps(tmp_repo, FakeRenderer(), tmp_path), _run(tmp_repo))
    with pytest.raises(ValidationFailed):
        promote_variant(tmp_repo, "shot_1", "E1_omni_restyle")  # nothing to promote yet
    repo_ps = PrevizShotRepo(tmp_repo.store)
    ps = repo_ps.active_for_shot("shot_1")
    assert ps is not None
    done = [
        PrevizVariantRecord(variant="E1_omni_restyle", status="done", video_uri=ps.previz_video_uri),
        PrevizVariantRecord(variant="E2_keyframe_restyle", status="done", video_uri=ps.previz_video_uri),
    ]  # fmt: skip
    repo_ps.put(ps.model_copy(update={"variants": done}))
    before = max(
        (r.attempt for r in tmp_repo.list_generation_runs(shot_id="shot_1")), default=0
    )
    promote_variant(tmp_repo, "shot_1", "E2_keyframe_restyle")
    out = promote_variant(tmp_repo, "shot_1", "E1_omni_restyle")
    runs = tmp_repo.list_generation_runs(shot_id="shot_1")
    latest = max(runs, key=lambda r: r.attempt)
    shot = tmp_repo.get_shot("shot_1")
    assert latest.attempt == before + 2 and latest.provider == "previz_E1_omni_restyle"
    assert (
        latest.status == Status.RENDERED
        and latest.shot_content_hash == shot.content_hash
    )  # type: ignore[union-attr]
    assert [v.promoted for v in out.variants] == [True, False]
    with pytest.raises(NotFound):
        promote_variant(tmp_repo, "shot_missing", "E1_omni_restyle")


@pytest.mark.parametrize(
    "body",
    [
        {"variant": "E3"},
        {"variant": "both", "scene_ids": ["scn_1; DROP"]},
        {"variant": "both", "scene_ids": ["../etc"]},
        {"variant": "both", "unexpected": True},
    ],
)
def test_run_payload_rejects_bad_input(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PrevizRunPayload.model_validate(body)


def test_payloads_accept_contract_values() -> None:
    ok = PrevizRunPayload.model_validate({"variant": "both", "scene_ids": ["scn_001"]})
    assert ok.scene_ids == ["scn_001"] and ok.force is False
    assert PrevizRunPayload().variant == "previz_only"
    with pytest.raises(ValidationError):
        PromotePrevizPayload.model_validate({"variant": "previz_only"})
