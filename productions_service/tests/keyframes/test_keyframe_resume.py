"""S8_KEYFRAMES under quota pressure: every shot recorded, resume reuses done work, force redoes.

Regression for production p-0irbygdv: a 429 escaped the scene worker, the stage aborted
after the other scenes finished, and the superseded shots were left with no keyframes and
no failure_reason. Model calls here go through a real `Governor` (fake clock) exactly like
`GeminiImageGenerator`, so a persistent 429 surfaces as `QuotaExhausted`.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from genai_governor.fakes import FakeClock, fake_governor, quota_error
from test_keyframe_stage import PLATE_MARK, PngImages, _deps, _sets, _two_clip_scene

from storygraph.adapters.governor import Governor
from storygraph.keyframes.animate.sources import StoredSource
from storygraph.keyframes.stage.scene_plans import shot_plan
from storygraph.keyframes.stage.stage import KeyframeStageResult, run_keyframe_stage
from storygraph.pipeline.keyframes.stage_adapter import (
    failure_summary,
    reset_keyframes,
)
from storygraph.repo import Repo

SHOTS = ("shot_1", "shot_2")


class ForeignProviderError(Exception):
    """Not a StoryGraphError (e.g. a google.api_core / httpx error from a fetch)."""


class GovernedImages:
    """`PngImages` behind a governor, like the real adapter's single seam."""

    def __init__(self, inner: PngImages, governor: Governor) -> None:
        self.inner, self.governor = inner, governor

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        aspect_ratio: str = "16:9",
        seed: int = 42,
    ) -> bytes:
        def request() -> bytes:
            return self.inner.generate(prompt, reference_images, aspect_ratio, seed)

        return self.governor.call("gemini-nano-banana-2.1", request)


class QuotaAfter(PngImages):
    """Keyframe calls succeed `ok` times, then 429 until `restore()`; plates always work."""

    def __init__(self, ok: int) -> None:
        super().__init__()
        self.left: int | None = ok

    def restore(self) -> None:
        self.left = None

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        aspect_ratio: str = "16:9",
        seed: int = 42,
    ) -> bytes:
        if PLATE_MARK not in prompt and self.left is not None:
            if self.left == 0:
                raise quota_error()
            self.left -= 1
        return super().generate(prompt, reference_images, aspect_ratio, seed)


def _run(repo: Repo, images: PngImages) -> KeyframeStageResult:
    governed = GovernedImages(images, fake_governor(FakeClock(), max_elapsed_s=30.0))
    return run_keyframe_stage(_deps(repo, governed))


def _plate_errors() -> list[Callable[[], Exception]]:
    return [quota_error, lambda: ForeignProviderError("GCS 429 TooManyRequests")]


@pytest.mark.parametrize("make_error", _plate_errors(), ids=["quota", "foreign"])
def test_plate_failure_records_every_clip_of_the_scene(
    tmp_repo: Repo, make_error: Callable[[], Exception]
) -> None:
    _two_clip_scene(tmp_repo)
    result = _run(tmp_repo, PngImages(always={"plate": make_error()}))  # must not raise
    assert sorted(result.failed) == list(SHOTS)
    for sid in SHOTS:
        ks = _sets(tmp_repo).active_for_shot(sid)
        assert ks is not None and not ks.frames and ks.needs_manual_edit
        assert ks.failure_reason.startswith("scene plate failed: ")
        shot = tmp_repo.get_shot(sid)
        assert shot is not None and shot.needs_manual_edit
    reason = result.failed["shot_1"]
    if "quota" in reason:
        assert "quota exhausted after" in reason and "attempt(s)" in reason
    summary = failure_summary(result) or ""
    assert "2 of 2 clips failed" in summary and "Resume keyframes" in summary


def test_quota_mid_shot_keeps_done_frames_and_resume_continues_there(
    tmp_repo: Repo,
) -> None:
    _two_clip_scene(tmp_repo)
    images = QuotaAfter(ok=3)
    first = _run(tmp_repo, images)
    assert sorted(first.failed) == list(SHOTS)
    failed = _sets(tmp_repo).active_for_shot("shot_1")
    assert failed is not None and failed.frames and failed.plan_hash
    kept = len(failed.frames)
    assert failed.failure_reason.startswith(f"at t={kept}: quota exhausted after")
    scene, shot = tmp_repo.get_scene("scn_1"), tmp_repo.get_shot("shot_1")
    assert scene is not None and shot is not None
    inp, plan = shot_plan(tmp_repo, scene, shot)
    assert StoredSource(tmp_repo).frames(inp, plan) is None  # partial never renders

    images.restore()
    resumed = _run(tmp_repo, images)
    assert sorted(resumed.rendered) == list(SHOTS) and not resumed.failed
    one, two = (_sets(tmp_repo).active_for_shot(s) for s in SHOTS)
    assert one is not None and two is not None and not one.failure_reason
    assert [f.asset_id for f in one.frames[:kept]] == [
        f.asset_id for f in failed.frames
    ]
    assert one.reason == f"S8_KEYFRAMES resume from t={kept}"
    assert two.frames[0].asset_id == one.frames[-1].asset_id  # chain restored
    assert images.count("plate") == 1  # plate reused on resume
    for sid in SHOTS:
        settled = tmp_repo.get_shot(sid)
        assert settled is not None and not settled.needs_manual_edit and settled.stale


def test_forced_regenerate_supersedes_every_set(tmp_repo: Repo) -> None:
    _two_clip_scene(tmp_repo)
    images = PngImages()
    _run(tmp_repo, images)
    before = {s: _sets(tmp_repo).active_for_shot(s) for s in SHOTS}
    assert reset_keyframes(tmp_repo) == 2
    calls = images.count("keyframe")
    forced = _run(tmp_repo, images)
    assert sorted(forced.rendered) == list(SHOTS) and images.count("keyframe") > calls
    for sid in SHOTS:
        old, new = before[sid], _sets(tmp_repo).active_for_shot(sid)
        assert old is not None and new is not None and new.version == old.version + 1
        owned = {f.asset_id for f in old.frames if not f.shared_from}
        assert owned.isdisjoint(f.asset_id for f in new.frames)
