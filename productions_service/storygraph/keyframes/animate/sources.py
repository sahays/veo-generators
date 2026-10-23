"""Where the render strategies get a shot's keyframes from.

* `StoredSource` (production): the shot's ACTIVE `KeyframeSet` written by S8_KEYFRAMES; only
  used when its plan hash still matches the graph (otherwise the stage must re-run).
* `RenderingSource` (experiments): renders on demand through `KeyframeRenderer`, sharing the
  previous clip's last keyframe as frame 0 of the next clip in the scene.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from ..plan.models import KeyframePlan, PlanInput
from ..render.renderer import KeyframeRenderer, RenderedKeyframe, RenderJob, ScenePlate
from ..stage.frames import to_rendered


class KeyframeSource(Protocol):
    def frames(
        self, inp: PlanInput, plan: KeyframePlan
    ) -> list[RenderedKeyframe] | None: ...


class StoredSource:
    """Approved keyframes from Firestore/GCS (None when missing or stale)."""

    def __init__(self, repo: Repo) -> None:
        self.sets = KeyframeSetRepo(repo.store)

    def frames(
        self, inp: PlanInput, plan: KeyframePlan
    ) -> list[RenderedKeyframe] | None:
        ks = self.sets.active_for_shot(plan.shot_id)
        if ks is None or ks.plan_hash != plan.plan_hash:
            return None
        return [to_rendered(f) for f in ks.frames]


def shared_copy(last: RenderedKeyframe, from_shot: str) -> RenderedKeyframe:
    """`last` (frame N of the previous clip) re-labelled as frame 0 of the next clip."""
    return replace(
        last, t=0, attempts=0, reused=True, shared_from=f"{from_shot}@t{last.t:02d}"
    )


class RenderingSource:
    """Render-on-demand source (cached per plan hash) for offline experiments."""

    def __init__(
        self, renderer: KeyframeRenderer, plate_for: Callable[[str], ScenePlate]
    ) -> None:
        self.renderer, self.plate_for = renderer, plate_for
        self._frames: dict[str, list[RenderedKeyframe]] = {}
        self._last: dict[tuple[str, int], tuple[str, RenderedKeyframe]] = {}

    def prime(self, plan: KeyframePlan, frames: list[RenderedKeyframe]) -> None:
        self._frames[plan.plan_hash] = frames

    def frames(
        self, inp: PlanInput, plan: KeyframePlan
    ) -> list[RenderedKeyframe] | None:
        if plan.plan_hash not in self._frames:
            prev = self._last.get((plan.scene_id, plan.clip_index - 1))
            shared = shared_copy(prev[1], prev[0]) if prev else None
            self._frames[plan.plan_hash] = self.renderer.render(
                inp,
                plan,
                RenderJob(plate=self.plate_for(plan.scene_id), shared_first=shared),
            )
        frames = self._frames[plan.plan_hash]
        self._last[(plan.scene_id, plan.clip_index)] = (plan.shot_id, frames[-1])
        return frames
