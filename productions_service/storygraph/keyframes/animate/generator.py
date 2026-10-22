"""`VideoGenerator` that animates a shot from its graph-correct 1 fps keyframes.

`render_strategy` (config `video.render_strategy`):
* direct           — delegate to the wrapped Omni generator unchanged;
* keyframe_interp  — chained <FIRST_FRAME>/<LAST_FRAME> segments every `keyframe_stride_s`
                     (rendered in parallel, then trimmed + stitched);
* animatic_edit    — 1 fps animatic MP4 stored as an asset and sent as <VIDEO_0>;
* keyframe_anchored(_text) — ONE request anchored on first/last keyframes (+ timed middle
                     state references, or their text in `_text`).
Keyframes come from a `KeyframeSource`: production reads the approved S8_KEYFRAMES set;
experiments render on demand. A shot without current keyframes falls back to `direct`
with a semantic WARNING (never silently).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

from ...adapters.base import VideoGenerator
from ...compile import Package
from ...config import VideoProviderCfg
from ...errors import StoryGraphError
from ...repo import Repo
from ..plan.graph_source import build_plan_input
from ..plan.models import KeyframePlan, PlanInput
from ..plan.planner import plan_keyframes
from ..render.renderer import RenderedKeyframe
from ..render.sink import KeyframeSink
from . import media, strategies
from .sources import KeyframeSource
from .timing import segment_bounds

_log = logging.getLogger(__name__)
Strategy = Literal[
    "direct",
    "keyframe_interp",
    "animatic_edit",
    "keyframe_anchored",
    "keyframe_anchored_text",
]


class KeyframeVideoGenerator:
    def __init__(
        self,
        inner: VideoGenerator,
        repo: Repo,
        source: KeyframeSource,
        sink: KeyframeSink,
        caps: VideoProviderCfg,
    ) -> None:
        self.inner, self.repo, self.source, self.sink = inner, repo, source, sink
        self.caps = caps

    def pop_fallback(self, shot_id: str) -> object | None:
        pop = getattr(self.inner, "pop_fallback", None)
        return pop(shot_id) if callable(pop) else None

    def plan_for(self, shot_id: str) -> tuple[PlanInput, KeyframePlan]:
        shot = self.repo.get_shot(shot_id)
        scene = self.repo.get_scene(shot.scene_id) if shot else None
        if shot is None or scene is None:
            raise StoryGraphError(f"keyframe strategy: unknown shot {shot_id}")
        inp = build_plan_input(self.repo, scene, shot)
        return inp, plan_keyframes(inp)

    def keyframes(self, inp: PlanInput, plan: KeyframePlan) -> list[RenderedKeyframe]:
        frames = self.source.frames(inp, plan)
        if not frames:
            raise StoryGraphError(f"no current keyframes for {plan.shot_id}")
        return frames

    def _png(self, frame: RenderedKeyframe) -> bytes:
        return frame.png or self.repo.blobs.get_bytes(frame.stored.uri)

    def _interp(
        self,
        package: Package,
        frames: list[RenderedKeyframe],
        inp: PlanInput,
        plan: KeyframePlan,
    ) -> bytes:
        bounds = segment_bounds(len(frames) - 1, self.caps.keyframe_stride_s)
        uris = [f.stored.uri for f in frames]
        pkgs = strategies.interp_packages(package, inp, uris, bounds)
        with ThreadPoolExecutor(max_workers=max(1, len(pkgs))) as pool:
            clips = list(pool.map(self.inner.generate, pkgs))
        return media.stitch(clips, strategies.plan_durations(plan, bounds))

    def _animatic(
        self,
        package: Package,
        frames: list[RenderedKeyframe],
        inp: PlanInput,
        plan: KeyframePlan,
    ) -> bytes:
        mp4 = media.build_animatic([self._png(f) for f in frames], plan.duration_s)
        stored = self.sink.save_animatic(plan, mp4)
        return self.inner.generate(
            strategies.animatic_package(package, inp, stored.uri)
        )

    def _anchored(
        self,
        package: Package,
        frames: list[RenderedKeyframe],
        inp: PlanInput,
        plan: KeyframePlan,
        state_refs: bool,
    ) -> bytes:
        uris = [f.stored.uri for f in frames]
        pkg = strategies.anchored_package(
            package, inp, plan, uris, self.caps.max_reference_images, state_refs
        )
        return self.inner.generate(pkg)

    def generate_with(self, package: Package, strategy: Strategy) -> bytes:
        if strategy == "direct":
            return self.inner.generate(package)
        inp, plan = self.plan_for(package.shot_id)
        frames = self.source.frames(inp, plan)
        if not frames:
            _log_strategy(package, plan, strategy, fallback=True)
            return self.inner.generate(package)
        _log_strategy(package, plan, strategy)
        if strategy == "keyframe_interp":
            return self._interp(package, frames, inp, plan)
        if strategy == "animatic_edit":
            return self._animatic(package, frames, inp, plan)
        return self._anchored(
            package, frames, inp, plan, strategy == "keyframe_anchored"
        )

    def generate(self, package: Package) -> bytes:
        return self.generate_with(package, self.caps.render_strategy)


def _log_strategy(
    package: Package, plan: KeyframePlan, strategy: str, fallback: bool = False
) -> None:
    level = logging.WARNING if fallback else logging.INFO
    _log.log(
        level,
        "keyframe render strategy" + (" fell back to direct" if fallback else ""),
        extra={
            "who": "storygraph.keyframes.generator",
            "where": f"{plan.project_id}/{package.shot_id}",
            "what": f"render {'direct' if fallback else strategy} ({len(plan.keyframes)} planned keyframes)",
            "when": datetime.now(UTC).isoformat(),
            "why": "no approved keyframes match the current plan; run S8_KEYFRAMES"
            if fallback
            else "video.render_strategy selects keyframe-driven animation",
            "how": "graph 1 fps plan -> edited keyframes -> Omni frame/video bindings",
            "plan_hash": plan.plan_hash,
        },
    )
