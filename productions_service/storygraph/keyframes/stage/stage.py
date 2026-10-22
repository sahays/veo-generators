"""S8_KEYFRAMES: derive, check and persist every shot's 1 fps keyframes (last step before video).

Per scene (scenes run in parallel), shots in clip order:
1. plan the clip from graph state (`plan.planner`) — N+1 keyframes for an N-second clip;
2. frame 0 of clip k+1 IS frame N of clip k (same asset, `shared_from`, never regenerated);
   the first clip of a scene starts from the identity/location sheets;
3. every other frame is an image edit of its predecessor, VLM-checked against graph state and
   the previous keyframe, regenerated up to `max_retries` times;
4. the result is stored as a new active `KeyframeSet` version (GCS images + Firestore set);
   frames still failing are `manual_edit` and the shot is flagged `needs_manual_edit` (render
   skips it until a human edits/regenerates its keyframes — the shot repair policy).
A shot whose active set still matches its plan and shared start frame is reused, not rerendered.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import Role, Scene, Shot
from ...schemas.keyframes import KeyframeSet
from ..animate.sources import shared_copy
from ..plan.graph_source import build_plan_input
from ..plan.models import KeyframePlan, PlanInput
from ..plan.planner import plan_keyframes
from ..render.renderer import KeyframeRenderer, RenderedKeyframe, RenderJob
from .frames import to_frame, to_rendered

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyframeStageDeps:
    repo: Repo
    renderer: KeyframeRenderer
    max_retries: int = 2
    scene_workers: int = 4


@dataclass
class KeyframeStageResult:
    rendered: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    manual_edit: list[str] = field(default_factory=list)

    def merge(self, other: KeyframeStageResult) -> None:
        self.rendered += other.rendered
        self.reused += other.reused
        self.manual_edit += other.manual_edit


def is_current(
    active: KeyframeSet | None, plan: KeyframePlan, prev: KeyframeSet | None
) -> bool:
    """Reuse `active` only if its plan is unchanged and it starts on `prev`'s last frame."""
    if active is None or active.plan_hash != plan.plan_hash or not active.frames:
        return False
    if prev is None:
        return active.frames[0].shared_from is None
    return active.frames[0].asset_id == prev.last.asset_id


def shared_start(repo: Repo, prev: KeyframeSet | None) -> RenderedKeyframe | None:
    """Clip k's stored last keyframe as clip k+1's frame 0 (pixels loaded for edits)."""
    if prev is None:
        return None
    last = prev.last
    return shared_copy(to_rendered(last, repo.blobs.get_bytes(last.uri)), prev.shot_id)


def build_set(
    shot: Shot,
    plan: KeyframePlan,
    frames: list[RenderedKeyframe],
    max_retries: int,
    reason: str,
) -> KeyframeSet:
    stored = [to_frame(rk, plan.at(rk.t), max_retries) for rk in frames]
    return KeyframeSet(
        id=f"kfs_{shot.id}",
        created_by=Role.PIPELINE,
        shot_id=shot.id,
        scene_id=shot.scene_id,
        clip_index=shot.clip_index or 0,
        plan_hash=plan.plan_hash,
        shot_content_hash=shot.content_hash,
        prompt_version_id=plan.prompt_version_id,
        duration_s=plan.duration_s,
        frames=stored,
        needs_manual_edit=any(f.status == "manual_edit" for f in stored),
        reason=reason,
    )


def flag_manual_edit(repo: Repo, shot: Shot, ks: KeyframeSet) -> None:
    """Shot repair policy: keyframes that fail every retry block render until edited."""
    reasons = [
        f"keyframe t={f.t}: {'; '.join(f.issues[:2])}"
        for f in ks.frames
        if f.status == "manual_edit"
    ]
    repo.put_shot(
        shot.model_copy(
            update={"needs_manual_edit": True, "manual_edit_reasons": reasons}
        )
    )


def plan_shot(repo: Repo, scene: Scene, shot: Shot) -> tuple[PlanInput, KeyframePlan]:
    inp = build_plan_input(repo, scene, shot)
    return inp, plan_keyframes(inp)


def ensure_shot(
    deps: KeyframeStageDeps, scene: Scene, shot: Shot, prev: KeyframeSet | None
) -> tuple[KeyframeSet, bool]:
    """(active set for `shot`, rendered?) — reuses a current set, else derives a new one."""
    sets = KeyframeSetRepo(deps.repo.store)
    inp, plan = plan_shot(deps.repo, scene, shot)
    active = sets.active_for_shot(shot.id)
    if active is not None and is_current(active, plan, prev):
        return active, False
    job = RenderJob(shared_first=shared_start(deps.repo, prev))
    frames = deps.renderer.render(inp, plan, job)
    ks = sets.create(
        build_set(shot, plan, frames, deps.max_retries, "S8_KEYFRAMES derive")
    )
    if ks.needs_manual_edit:
        flag_manual_edit(deps.repo, shot, ks)
    return ks, True


def run_scene(deps: KeyframeStageDeps, scene: Scene) -> KeyframeStageResult:
    out = KeyframeStageResult()
    prev: KeyframeSet | None = None
    shots = sorted(
        deps.repo.list_shots(scene_id=scene.id), key=lambda s: s.clip_index or 0
    )
    for shot in shots:
        if shot.clip_index is None:
            continue
        prev, rendered = ensure_shot(deps, scene, shot, prev)
        (out.rendered if rendered else out.reused).append(shot.id)
        if prev.needs_manual_edit:
            out.manual_edit.append(shot.id)
    return out


def run_keyframe_stage(deps: KeyframeStageDeps) -> KeyframeStageResult:
    """Derive/reuse keyframes for every shot; scenes in parallel, clips sequential."""
    scenes = deps.repo.list_scenes()
    result = KeyframeStageResult()
    with ThreadPoolExecutor(
        max_workers=max(1, min(deps.scene_workers, len(scenes) or 1))
    ) as pool:
        for part in pool.map(lambda sc: run_scene(deps, sc), scenes):
            result.merge(part)
    _log.info(
        "S8_KEYFRAMES complete",
        extra={
            "who": "storygraph.keyframes.stage",
            "where": f"project/{getattr(deps.repo.store, 'project_id', '')}",
            "what": f"{len(result.rendered)} derived, {len(result.reused)} reused, "
            f"{len(result.manual_edit)} need manual edit",
            "when": datetime.now(UTC).isoformat(),
            "why": "graph-correct 1 fps keyframes are the render inputs",
            "how": "plan -> edit chain -> VLM check (<=2 retries) -> KeyframeSet version",
            "manual_edit_shots": result.manual_edit,
        },
    )
    return result
