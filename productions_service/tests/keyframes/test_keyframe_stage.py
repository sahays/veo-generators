"""S8_KEYFRAMES: plate per scene, frame sharing, reuse, drift guard, failure isolation."""

from __future__ import annotations

import io

import pytest
from conftest import add_clip_shot, seed_valid_graph, set_scene_clips
from PIL import Image
from pydantic import BaseModel

from storygraph.adapters.mock import MockVLMProvider
from storygraph.errors import StoryGraphError, ValidationFailed
from storygraph.keyframes.animate.sources import StoredSource
from storygraph.keyframes.plate.build import PlateBuilder
from storygraph.keyframes.render import retry
from storygraph.keyframes.render.renderer import KeyframeRenderer, RendererCfg
from storygraph.keyframes.render.sink import RepoKeyframeSink
from storygraph.keyframes.render.validation import KeyframeCheck
from storygraph.keyframes.stage.regenerate import regenerate_from
from storygraph.keyframes.stage.scene_plans import shot_plan
from storygraph.keyframes.stage.stage import KeyframeStageDeps, run_keyframe_stage
from storygraph.repo import Repo
from storygraph.repo.keyframe_sets import KeyframeSetRepo
from storygraph.schema import InteractionStep

PLATE_MARK = "EMPTY-SET MASTER PLATE"
Rgb = tuple[int, int, int]


class PngImages:
    """ImageGenerator fake: real 64x36 PNGs, one pixel moved per call (distinct bytes,
    identical statistics -> drift ~0). `fail[kind]` errors are raised once each, in order;
    `always[kind]` is raised on every call of that kind (plate | keyframe)."""

    def __init__(
        self,
        plate_rgb: Rgb = (90, 120, 160),
        frame_rgb: Rgb | None = None,
        fail: dict[str, list[Exception]] | None = None,
        always: dict[str, Exception] | None = None,
    ) -> None:
        self.plate_rgb, self.frame_rgb = plate_rgb, frame_rgb or plate_rgb
        self.fail, self.always = fail or {}, always or {}
        self.calls: list[str] = []

    def _png(self, rgb: Rgb) -> bytes:
        img = Image.new("RGB", (64, 36), rgb)
        n = len(self.calls)
        img.putpixel((n % 64, (n // 64) % 36), (rgb[0], rgb[1], min(255, rgb[2] + 1)))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        aspect_ratio: str = "16:9",
        seed: int = 42,
    ) -> bytes:
        kind = "plate" if PLATE_MARK in prompt else "keyframe"
        self.calls.append(kind)
        if kind in self.always:
            raise self.always[kind]
        if self.fail.get(kind):
            raise self.fail[kind].pop(0)
        return self._png(self.plate_rgb if kind == "plate" else self.frame_rgb)

    def count(self, kind: str) -> int:
        return self.calls.count(kind)


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
    repo: Repo, images: PngImages, vlm: MockVLMProvider | None = None
) -> KeyframeStageDeps:
    vlm = vlm or MockVLMProvider()
    sink = RepoKeyframeSink(repo)
    renderer = KeyframeRenderer(
        images, vlm, sink, repo.blobs.get_bytes, RendererCfg(model="fake")
    )
    plates = PlateBuilder(images, vlm, repo.blobs.get_bytes, "16:9")
    return KeyframeStageDeps(repo, renderer, sink, plates, "fake")


def _sets(repo: Repo) -> KeyframeSetRepo:
    return KeyframeSetRepo(repo.store)


def test_last_keyframe_of_clip_is_first_of_next_and_never_regenerated(
    tmp_repo: Repo,
) -> None:
    _two_clip_scene(tmp_repo)
    images = PngImages()
    result = run_keyframe_stage(_deps(tmp_repo, images))
    first = _sets(tmp_repo).active_for_shot("shot_1")
    second = _sets(tmp_repo).active_for_shot("shot_2")
    assert first is not None and second is not None
    assert len(first.frames) == len(second.frames) == 9  # 8 s clips -> t = 0..8
    assert second.frames[0].asset_id == first.frames[-1].asset_id
    assert second.frames[0].shared_from == "shot_1@t08"
    assert first.frames[0].shared_from is None
    assert sorted(result.rendered) == ["shot_1", "shot_2"] and not result.manual_edit
    # Rerun: sets and plate still current -> reused, no image calls at all (plate too).
    calls = len(images.calls)
    rerun = run_keyframe_stage(_deps(tmp_repo, images))
    assert sorted(rerun.reused) == ["shot_1", "shot_2"] and len(images.calls) == calls


def test_plate_generated_once_per_scene_and_linked_from_every_set(
    tmp_repo: Repo,
) -> None:
    _two_clip_scene(tmp_repo)
    images = PngImages()
    run_keyframe_stage(_deps(tmp_repo, images))
    assert images.count("plate") == 1
    assert images.calls[0] == "plate"  # keyframes are anchored on an existing plate
    ids = {
        ks.plate_asset_id
        for ks in (_sets(tmp_repo).active_for_shot(s) for s in ("shot_1", "shot_2"))
        if ks is not None
    }
    assert len(ids) == 1
    plate_id = ids.pop()
    assert plate_id and plate_id.startswith("ast_plate_scn_1_")
    assert tmp_repo.get_asset(plate_id) is not None


def _always_wrong(
    images: list[bytes], prompt: str, schema: type[BaseModel]
) -> BaseModel:
    return KeyframeCheck() if schema is KeyframeCheck else schema.model_validate({})


def test_failing_checks_retry_twice_then_flag_manual_edit(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    vlm = MockVLMProvider(custom_responder=_always_wrong)
    result = run_keyframe_stage(_deps(tmp_repo, PngImages(), vlm))
    ks = _sets(tmp_repo).active_for_shot("shot_1")
    assert ks is not None and ks.needs_manual_edit
    owned = [f for f in ks.frames if not f.shared_from and f.attempts]
    assert owned and all(f.attempts == 3 and f.status == "manual_edit" for f in owned)
    shot = tmp_repo.get_shot("shot_1")
    assert shot is not None and shot.needs_manual_edit and shot.manual_edit_reasons
    assert "shot_1" in result.manual_edit


def test_background_drift_rejected_without_asking_the_vlm(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    vlm = MockVLMProvider()
    images = PngImages(plate_rgb=(30, 60, 200), frame_rgb=(128, 128, 128))
    result = run_keyframe_stage(_deps(tmp_repo, images, vlm))
    ks = _sets(tmp_repo).active_for_shot("shot_1")
    assert ks is not None and ks.needs_manual_edit
    owned = [f for f in ks.frames if f.attempts]
    assert owned and all(f.status == "manual_edit" and f.attempts == 3 for f in owned)
    assert all(f.issues[0].startswith("background drift") for f in owned)
    assert all(f.drift.get("bad_fraction", 0.0) > 0.5 for f in owned)
    assert "KeyframeCheck" not in {c["schema"] for c in vlm.calls}
    assert sorted(result.manual_edit) == ["shot_1", "shot_2"]


def test_provider_error_is_isolated_per_shot(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    images = PngImages(always={"keyframe": StoryGraphError("400 bad request")})
    result = run_keyframe_stage(_deps(tmp_repo, images))  # must not raise
    assert sorted(result.failed) == ["shot_1", "shot_2"]
    assert images.count("keyframe") == 2  # non-transient: no retries
    for sid in ("shot_1", "shot_2"):
        ks = _sets(tmp_repo).active_for_shot(sid)
        assert ks is not None and not ks.frames
        assert "400 bad request" in (ks.failure_reason or "")
        shot = tmp_repo.get_shot(sid)
        assert shot is not None and shot.needs_manual_edit
        assert shot.manual_edit_reasons[0].startswith("keyframes failed:")


def test_transient_quota_errors_are_retried_with_backoff(
    tmp_repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(retry.time, "sleep", sleeps.append)
    base = 8.0  # with_retry default back-off base
    _two_clip_scene(tmp_repo)
    quota = [StoryGraphError("429 RESOURCE_EXHAUSTED") for _ in range(2)]
    images = PngImages(fail={"plate": quota})  # two transient failures, then success
    result = run_keyframe_stage(_deps(tmp_repo, images))
    assert sorted(result.rendered) == ["shot_1", "shot_2"] and not result.failed
    assert images.count("plate") == 3 and sleeps[:2] == [base, base * 2]


def test_regenerate_rederives_tail_and_cascades_to_next_clip(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    deps = _deps(tmp_repo, PngImages())
    run_keyframe_stage(deps)
    before1 = _sets(tmp_repo).active_for_shot("shot_1")
    assert before1 is not None
    with pytest.raises(ValidationFailed):
        regenerate_from(deps, "shot_2", 0)  # shared frame belongs to the previous clip
    after1 = regenerate_from(deps, "shot_1", 3, "make the compass brighter")
    after2 = _sets(tmp_repo).active_for_shot("shot_2")
    assert after1.version == 2 and after2 is not None and after2.version == 2
    kept = [f.asset_id for f in before1.frames[:3]]
    assert [f.asset_id for f in after1.frames[:3]] == kept
    assert after1.frames[3].asset_id != before1.frames[3].asset_id
    assert after1.frames[3].edited_by == "human"
    assert after2.frames[0].asset_id == after1.frames[-1].asset_id
    shots = {s.id: s for s in tmp_repo.list_shots()}
    assert shots["shot_1"].stale and shots["shot_2"].stale


def test_stored_source_uses_scene_plan_and_ignores_older_plans(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    run_keyframe_stage(_deps(tmp_repo, PngImages()))
    scene, shot = tmp_repo.get_scene("scn_1"), tmp_repo.get_shot("shot_2")
    assert scene is not None and shot is not None
    inp, plan = shot_plan(tmp_repo, scene, shot)
    assert StoredSource(tmp_repo).frames(inp, plan)
    changed = plan.model_copy(update={"plan_hash": "different"})
    assert StoredSource(tmp_repo).frames(inp, changed) is None
