"""S8_KEYFRAMES: cross-clip frame sharing, reuse, manual-edit policy, regenerate cascade."""

from __future__ import annotations

import pytest
from conftest import add_clip_shot, seed_valid_graph, set_scene_clips
from pydantic import BaseModel
from storygraph.adapters.mock import MockVLMProvider
from storygraph.errors import ValidationFailed
from storygraph.keyframes.animate.sources import StoredSource
from storygraph.keyframes.plan.graph_source import build_plan_input
from storygraph.keyframes.plan.planner import plan_keyframes
from storygraph.keyframes.render.renderer import KeyframeRenderer, RendererCfg
from storygraph.keyframes.render.sink import RepoKeyframeSink
from storygraph.keyframes.render.validation import KeyframeCheck
from storygraph.keyframes.stage.regenerate import regenerate_from
from storygraph.keyframes.stage.stage import KeyframeStageDeps, run_keyframe_stage
from storygraph.repo import Repo
from storygraph.repo.keyframe_sets import KeyframeSetRepo
from storygraph.schema import InteractionStep


class CountingImages:
    """ImageGenerator fake: distinct bytes per call, counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        aspect_ratio: str = "16:9",
        seed: int = 42,
    ) -> bytes:
        self.calls += 1
        return b"\x89PNG-fake-" + str(self.calls).encode()


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
    repo: Repo, images: CountingImages, vlm: MockVLMProvider | None = None
) -> KeyframeStageDeps:
    renderer = KeyframeRenderer(
        images, vlm or MockVLMProvider(), RepoKeyframeSink(repo), repo.blobs.get_bytes,
        RendererCfg(model="fake"),
    )  # fmt: skip
    return KeyframeStageDeps(repo=repo, renderer=renderer)


def test_last_keyframe_of_clip_is_first_of_next_and_never_regenerated(
    tmp_repo: Repo,
) -> None:
    _two_clip_scene(tmp_repo)
    images = CountingImages()
    result = run_keyframe_stage(_deps(tmp_repo, images))
    sets = KeyframeSetRepo(tmp_repo.store)
    first, second = sets.active_for_shot("shot_1"), sets.active_for_shot("shot_2")
    assert first is not None and second is not None
    assert len(first.frames) == len(second.frames) == 9  # 8 s clips -> t = 0..8
    assert second.frames[0].asset_id == first.frames[-1].asset_id
    assert second.frames[0].shared_from == "shot_1@t08"
    assert first.frames[0].shared_from is None
    assert sorted(result.rendered) == ["shot_1", "shot_2"] and not result.manual_edit
    # Rerun: both sets still current -> reused, no image calls at all.
    calls = images.calls
    rerun = run_keyframe_stage(_deps(tmp_repo, images))
    assert sorted(rerun.reused) == ["shot_1", "shot_2"] and images.calls == calls


def _always_wrong(
    images: list[bytes], prompt: str, schema: type[BaseModel]
) -> BaseModel:
    return KeyframeCheck() if schema is KeyframeCheck else schema.model_validate({})


def test_failing_checks_retry_twice_then_flag_manual_edit(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    result = run_keyframe_stage(
        _deps(
            tmp_repo, CountingImages(), MockVLMProvider(custom_responder=_always_wrong)
        )
    )
    ks = KeyframeSetRepo(tmp_repo.store).active_for_shot("shot_1")
    assert ks is not None and ks.needs_manual_edit
    owned = [f for f in ks.frames if not f.shared_from and f.attempts]
    assert owned and all(f.attempts == 3 and f.status == "manual_edit" for f in owned)
    shot = tmp_repo.get_shot("shot_1")
    assert shot is not None and shot.needs_manual_edit and shot.manual_edit_reasons
    assert "shot_1" in result.manual_edit


def test_regenerate_rederives_tail_and_cascades_to_next_clip(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    images = CountingImages()
    deps = _deps(tmp_repo, images)
    run_keyframe_stage(deps)
    sets = KeyframeSetRepo(tmp_repo.store)
    before1, before2 = sets.active_for_shot("shot_1"), sets.active_for_shot("shot_2")
    assert before1 is not None and before2 is not None
    with pytest.raises(ValidationFailed):
        regenerate_from(deps, "shot_2", 0)  # shared frame belongs to the previous clip
    after1 = regenerate_from(deps, "shot_1", 3, "make the compass brighter")
    after2 = sets.active_for_shot("shot_2")
    assert after1.version == 2 and after2 is not None and after2.version == 2
    assert [f.asset_id for f in after1.frames[:3]] == [
        f.asset_id for f in before1.frames[:3]
    ]
    assert after1.frames[3].asset_id != before1.frames[3].asset_id
    assert after1.frames[3].edited_by == "human"
    assert after2.frames[0].asset_id == after1.frames[-1].asset_id
    shots = {s.id: s for s in tmp_repo.list_shots()}
    assert shots["shot_1"].stale and shots["shot_2"].stale


def test_stored_source_ignores_sets_from_an_older_plan(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    run_keyframe_stage(_deps(tmp_repo, CountingImages()))
    scene, shot = tmp_repo.get_scene("scn_1"), tmp_repo.get_shot("shot_1")
    assert scene is not None and shot is not None
    inp = build_plan_input(tmp_repo, scene, shot)
    plan = plan_keyframes(inp)
    assert StoredSource(tmp_repo).frames(inp, plan)
    changed = plan.model_copy(update={"plan_hash": "different"})
    assert StoredSource(tmp_repo).frames(inp, changed) is None
