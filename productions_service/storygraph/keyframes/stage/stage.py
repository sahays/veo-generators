"""S8_KEYFRAMES: derive, check and persist every shot's 1 fps keyframes (last step before video).

Per scene (scenes run in parallel), shots in clip order:
1. plan every clip from graph state; build (or reuse by spec hash) the scene's locked
   empty-set plate and re-plan the clips against its layout, carrying character positions
   from clip to clip (`scene_plans`);
2. frame 0 of clip k+1 IS frame N of clip k (same asset, `shared_from`, never regenerated);
3. every other frame is generated at constant depth from plate + labelled ref board (+ the
   previous frame as a pose reference), drift-guarded against the plate, VLM-checked per
   entity and regenerated up to `max_retries` times;
4. the result is stored as a new active `KeyframeSet` version (GCS images + Firestore set);
   frames still failing are `manual_edit` and the shot is flagged `needs_manual_edit`.
A shot whose active set matches its plan, plate and shared start frame is reused. A shot
(or scene) whose derivation raises is recorded as a failed set with `failure_reason`, flagged
for manual edit and logged — the rest of the scene and the other scenes still run.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...errors import StoryGraphError
from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import Role, Scene, Shot
from ...schemas.keyframes import KeyframeSet
from ..animate.sources import shared_copy
from ..plan.models import KeyframePlan
from ..plate.build import PlateBuilder
from ..render.renderer import KeyframeRenderer, RenderedKeyframe, RenderJob, ScenePlate
from ..render.sink import PlateStore
from .frames import to_frame, to_rendered
from .scene_plans import ShotPlan, chain_plans, scene_planning

_log = logging.getLogger(__name__)
# Failures isolated per shot/scene: provider errors, bad graph data, decode errors.
ISOLATED_ERRORS = (StoryGraphError, ValueError, KeyError, OSError, RuntimeError)


@dataclass(frozen=True)
class KeyframeStageDeps:
    repo: Repo
    renderer: KeyframeRenderer
    plates: PlateStore
    plate_builder: PlateBuilder
    plate_model: str = ""
    max_retries: int = 2
    scene_workers: int = 4


@dataclass
class KeyframeStageResult:
    rendered: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    manual_edit: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    def merge(self, other: KeyframeStageResult) -> None:
        self.rendered += other.rendered
        self.reused += other.reused
        self.manual_edit += other.manual_edit
        self.failed |= other.failed


@dataclass(frozen=True)
class SceneContext:
    scene: Scene
    plate: ScenePlate
    plans: dict[str, ShotPlan]


def scene_context(deps: KeyframeStageDeps, scene: Scene) -> SceneContext | None:
    """Plate (cached by spec key, else generated + stored) and layout-aware clip plans."""
    planning = scene_planning(deps.repo, scene)
    if planning.spec is None:
        return None
    spec = planning.spec
    stored = deps.plates.load_plate(spec)
    if stored is None:
        built = deps.plate_builder.generate(spec)
        stored = deps.plates.save_plate(spec, built, deps.plate_model)
    pieces = frozenset(o.entity_id for o in spec.set_pieces)
    plate = ScenePlate(stored.png, stored.asset_id, stored.uri, pieces)
    plans = chain_plans(planning.shots, planning.inputs, stored.layout)
    return SceneContext(scene, plate, {sp.shot.id: sp for sp in plans})


def is_current(
    active: KeyframeSet | None,
    plan: KeyframePlan,
    prev: KeyframeSet | None,
    plate_asset_id: str | None = None,
) -> bool:
    """Reuse `active` only if plan + plate are unchanged and it starts on `prev`'s last frame."""
    if active is None or active.plan_hash != plan.plan_hash or not active.frames:
        return False
    if plate_asset_id is not None and active.plate_asset_id != plate_asset_id:
        return False
    if prev is None or not prev.frames:
        return active.frames[0].shared_from is None
    return active.frames[0].asset_id == prev.last.asset_id


def shared_start(repo: Repo, prev: KeyframeSet | None) -> RenderedKeyframe | None:
    """Clip k's stored last keyframe as clip k+1's frame 0 (pixels loaded as pose ref)."""
    if prev is None or not prev.frames:
        return None
    last = prev.last
    return shared_copy(to_rendered(last, repo.blobs.get_bytes(last.uri)), prev.shot_id)


def build_set(
    shot: Shot,
    plan: KeyframePlan,
    frames: list[RenderedKeyframe],
    max_retries: int,
    reason: str,
    plate_asset_id: str | None = None,
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
        plate_asset_id=plate_asset_id,
    )


def flag_manual_edit(repo: Repo, shot: Shot, ks: KeyframeSet) -> None:
    """Shot repair policy: keyframes that fail every retry block render until edited."""
    reasons = [
        f"keyframe t={f.t}: {'; '.join(f.issues[:2])}"
        for f in ks.frames
        if f.status == "manual_edit"
    ]
    if ks.failure_reason:
        reasons.insert(0, f"keyframes failed: {ks.failure_reason}")
    repo.put_shot(
        shot.model_copy(
            update={"needs_manual_edit": True, "manual_edit_reasons": reasons}
        )
    )


def record_failure(deps: KeyframeStageDeps, shot: Shot, exc: Exception) -> KeyframeSet:
    """A visible failed set (no frames) + blocked shot instead of a silently missing shot."""
    reason = f"{type(exc).__name__}: {exc}"[:300]
    ks = KeyframeSetRepo(deps.repo.store).create(
        KeyframeSet(
            id=f"kfs_{shot.id}",
            created_by=Role.PIPELINE,
            shot_id=shot.id,
            scene_id=shot.scene_id,
            clip_index=shot.clip_index or 0,
            plan_hash="",
            duration_s=shot.duration_s,
            needs_manual_edit=True,
            reason="S8_KEYFRAMES failed",
            failure_reason=reason,
        )
    )
    flag_manual_edit(deps.repo, shot, ks)
    _log_failure(deps, shot, reason)
    return ks


def ensure_shot(
    deps: KeyframeStageDeps, ctx: SceneContext, shot: Shot, prev: KeyframeSet | None
) -> tuple[KeyframeSet, bool]:
    """(active set for `shot`, rendered?) — reuses a current set, else derives a new one."""
    sets = KeyframeSetRepo(deps.repo.store)
    sp = ctx.plans[shot.id]
    active = sets.active_for_shot(shot.id)
    if active is not None and is_current(active, sp.plan, prev, ctx.plate.asset_id):
        return active, False
    job = RenderJob(plate=ctx.plate, shared_first=shared_start(deps.repo, prev))
    frames = deps.renderer.render(sp.inp, sp.plan, job)
    draft = build_set(
        shot,
        sp.plan,
        frames,
        deps.max_retries,
        "S8_KEYFRAMES derive",
        ctx.plate.asset_id,
    )
    ks = sets.create(draft)
    if ks.needs_manual_edit:
        flag_manual_edit(deps.repo, shot, ks)
    return ks, True


def _scene_failed(
    deps: KeyframeStageDeps, scene: Scene, exc: Exception
) -> KeyframeStageResult:
    out = KeyframeStageResult()
    for shot in deps.repo.list_shots(scene_id=scene.id):
        if shot.clip_index is not None:
            out.failed[shot.id] = record_failure(deps, shot, exc).failure_reason
    return out


def run_scene(deps: KeyframeStageDeps, scene: Scene) -> KeyframeStageResult:
    try:
        ctx = scene_context(deps, scene)
    except ISOLATED_ERRORS as exc:
        return _scene_failed(deps, scene, exc)
    out = KeyframeStageResult()
    if ctx is None:
        return out
    prev: KeyframeSet | None = None
    for sp in ctx.plans.values():
        try:
            prev, rendered = ensure_shot(deps, ctx, sp.shot, prev)
        except ISOLATED_ERRORS as exc:
            prev = None
            out.failed[sp.shot.id] = record_failure(deps, sp.shot, exc).failure_reason
            continue
        (out.rendered if rendered else out.reused).append(sp.shot.id)
        if prev.needs_manual_edit:
            out.manual_edit.append(sp.shot.id)
    return out


def run_keyframe_stage(deps: KeyframeStageDeps) -> KeyframeStageResult:
    """Derive/reuse keyframes for every shot; scenes in parallel, clips sequential."""
    scenes = deps.repo.list_scenes()
    result = KeyframeStageResult()
    workers = max(1, min(deps.scene_workers, len(scenes) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(lambda sc: run_scene(deps, sc), scenes):
            result.merge(part)
    _log_complete(deps, result)
    return result


def _log_failure(deps: KeyframeStageDeps, shot: Shot, reason: str) -> None:
    _log.error(
        "S8_KEYFRAMES shot failed",
        extra={
            "who": "storygraph.keyframes.stage",
            "where": f"project/{deps.repo.project_id}/{shot.scene_id}/{shot.id}",
            "what": "keyframe derivation failed; failed set recorded, shot flagged",
            "when": datetime.now(UTC).isoformat(),
            "why": reason,
            "how": "per-shot isolation: the scene continues from a fresh start frame",
        },
    )


def _log_complete(deps: KeyframeStageDeps, result: KeyframeStageResult) -> None:
    _log.info(
        "S8_KEYFRAMES complete",
        extra={
            "who": "storygraph.keyframes.stage",
            "where": f"project/{deps.repo.project_id}",
            "what": f"{len(result.rendered)} derived, {len(result.reused)} reused, "
            f"{len(result.manual_edit)} need manual edit, {len(result.failed)} failed",
            "when": datetime.now(UTC).isoformat(),
            "why": "graph-correct 1 fps keyframes are the render inputs",
            "how": "scene plate -> constant-depth generation -> drift guard -> VLM check",
            "manual_edit_shots": result.manual_edit,
            "failed_shots": result.failed,
        },
    )
