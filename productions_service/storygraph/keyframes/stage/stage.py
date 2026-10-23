"""S8_KEYFRAMES: derive, check and persist every shot's 1 fps keyframes (last step before video).

Work queue: scenes are independent and run in parallel (`scene_workers`, from config); inside
a scene, shots and their frames are chained, so they run in clip / second order:
1. plan every clip from graph state; build (or reuse by spec hash) the scene's locked
   empty-set plate and re-plan the clips against its layout (`scene_plans`);
2. frame 0 of clip k+1 IS frame N of clip k (same asset, `shared_from`, never regenerated);
3. every other frame is generated at constant depth from plate + labelled ref board (+ the
   previous frame as a pose reference), drift-guarded, VLM-checked and regenerated up to
   `max_retries` times; model quota/capacity is handled by the process GenAI governor;
4. the result is stored as a new active `KeyframeSet` version.

Every shot ends in a recorded terminal state (`outcomes`): approved, manual_edit, or failed
(failed set with `failure_reason` + the frames finished before the failure). A plate failure
fails every shot of its scene with that reason. Non-forced runs are resumable (`resume`):
current sets are reused and a failed set continues at its first missing second. A forced run
supersedes every set first (pipeline runner) and so re-derives everything.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...adapters.governor import call_scope
from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import Role, Scene, Shot
from ...schemas.keyframes import KeyframeSet
from ..animate.sources import shared_copy
from ..plan.models import KeyframePlan
from ..plate.build import PlateBuilder
from ..render.renderer import (
    KeyframeRenderer,
    RenderedKeyframe,
    RenderInterrupted,
    RenderJob,
    ScenePlate,
)
from ..render.sink import PlateStore
from .frames import to_frame, to_rendered
from .outcomes import failure_text, record_failure, settle_shot
from .resume import is_current, prior_frames, resume_point
from .scene_plans import ShotPlan, chain_plans, scene_planning, scene_shots

_log = logging.getLogger(__name__)
STAGE = "S8_KEYFRAMES"


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

    @property
    def settled(self) -> set[str]:
        return {*self.rendered, *self.reused, *self.failed}


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


def _job(
    deps: KeyframeStageDeps,
    ctx: SceneContext,
    active: KeyframeSet | None,
    keep: int,
    prev: KeyframeSet | None,
) -> RenderJob:
    if keep and active is not None:  # resume a failed set at its first missing second
        prior = prior_frames(deps.repo, active, keep)
        return RenderJob(ctx.plate, prior=prior, start=keep, regenerate_start=False)
    return RenderJob(ctx.plate, shared_first=shared_start(deps.repo, prev))


def ensure_shot(
    deps: KeyframeStageDeps, ctx: SceneContext, shot: Shot, prev: KeyframeSet | None
) -> tuple[KeyframeSet, bool]:
    """(active set for `shot`, rendered?) — reuses a current set, resumes a failed one,
    else derives a new one. Raises `RenderInterrupted` with the frames stored so far."""
    sets = KeyframeSetRepo(deps.repo.store)
    sp = ctx.plans[shot.id]
    active = sets.active_for_shot(shot.id)
    if is_current(active, sp.plan, prev, ctx.plate.asset_id):
        assert active is not None
        return active, False
    keep = resume_point(active, sp.plan, prev, ctx.plate.asset_id)
    frames = deps.renderer.render(sp.inp, sp.plan, _job(deps, ctx, active, keep, prev))
    why = f"{STAGE} resume from t={keep}" if keep else f"{STAGE} derive"
    draft = build_set(shot, sp.plan, frames, deps.max_retries, why, ctx.plate.asset_id)
    ks = sets.create(draft)
    stale = f"keyframes re-derived ({STAGE})" if ks.version > 1 else None
    settle_shot(deps.repo, shot, ks, stale)
    return ks, True


def _partial(
    deps: KeyframeStageDeps, ctx: SceneContext, shot: Shot, exc: Exception
) -> KeyframeSet | None:
    """The frames stored before a mid-shot failure, as a (to-be-failed) set draft."""
    if not isinstance(exc, RenderInterrupted) or not exc.frames:
        return None
    sp = ctx.plans[shot.id]
    frames = list(exc.frames)
    reason = f"{STAGE} failed"
    return build_set(
        shot, sp.plan, frames, deps.max_retries, reason, ctx.plate.asset_id
    )


def _shot_failed(
    deps: KeyframeStageDeps, ctx: SceneContext, shot: Shot, exc: Exception
) -> str:
    cause = exc.cause if isinstance(exc, RenderInterrupted) else exc
    partial = _partial(deps, ctx, shot, exc)
    where = f"at t={exc.t}: " if isinstance(exc, RenderInterrupted) else ""
    return record_failure(deps.repo, shot, where + failure_text(cause), partial)


def _run_shots(deps: KeyframeStageDeps, ctx: SceneContext) -> KeyframeStageResult:
    out, prev = KeyframeStageResult(), None
    for sp in ctx.plans.values():
        with call_scope(STAGE, sp.shot.id):
            try:
                prev, rendered = ensure_shot(deps, ctx, sp.shot, prev)
            except Exception as exc:  # noqa: BLE001 - per-shot isolation boundary
                prev = None  # the next clip starts from a fresh frame 0
                out.failed[sp.shot.id] = _shot_failed(deps, ctx, sp.shot, exc)
                continue
        (out.rendered if rendered else out.reused).append(sp.shot.id)
        if prev.needs_manual_edit:
            out.manual_edit.append(sp.shot.id)
    return out


def _fail_rest(
    deps: KeyframeStageDeps, scene: Scene, done: set[str], reason: str
) -> KeyframeStageResult:
    """Every clip of `scene` not already settled is failed with `reason`."""
    out = KeyframeStageResult()
    try:
        shots = scene_shots(deps.repo, scene)
    except Exception as exc:  # noqa: BLE001 - nothing to record against
        _log_scene(deps, scene, f"clips unreadable: {failure_text(exc)}")
        return out
    for shot in shots:
        if shot.id not in done:
            out.failed[shot.id] = record_failure(deps.repo, shot, reason)
    return out


def run_scene(deps: KeyframeStageDeps, scene: Scene) -> KeyframeStageResult:
    """One scene to terminal states; a plate failure fails all of its clips."""
    with call_scope(STAGE, f"{scene.id}/plate"):
        try:
            ctx = scene_context(deps, scene)
        except Exception as exc:  # noqa: BLE001 - per-scene isolation boundary
            reason = f"scene plate failed: {failure_text(exc)}"
            return _fail_rest(deps, scene, set(), reason)
    return _run_shots(deps, ctx) if ctx is not None else KeyframeStageResult()


def _guarded(deps: KeyframeStageDeps, scene: Scene) -> KeyframeStageResult:
    """`run_scene`, but an unexpected crash still fails the scene's unsettled clips."""
    try:
        return run_scene(deps, scene)
    except Exception as exc:  # noqa: BLE001 - last-resort scene boundary
        settled = set(KeyframeSetRepo(deps.repo.store).active_by_shot())
        return _fail_rest(deps, scene, settled, f"scene crashed: {failure_text(exc)}")


def run_keyframe_stage(deps: KeyframeStageDeps) -> KeyframeStageResult:
    """Derive/reuse keyframes for every shot; scenes in parallel, clips sequential."""
    scenes = deps.repo.list_scenes()
    result = KeyframeStageResult()
    workers = max(1, min(deps.scene_workers, len(scenes) or 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kf") as pool:
        futures: list[Future[KeyframeStageResult]] = [
            pool.submit(_guarded, deps, sc) for sc in scenes
        ]
        for fut in as_completed(futures):
            result.merge(fut.result())
    _log_complete(deps, result)
    return result


def _log_scene(deps: KeyframeStageDeps, scene: Scene, why: str) -> None:
    _log.error(
        f"{STAGE} scene failed",
        extra={
            "who": "storygraph.keyframes.stage",
            "where": f"project/{deps.repo.project_id}/{scene.id}",
            "what": "scene could not be processed",
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "scene isolation: other scenes continue",
        },
    )


def _log_complete(deps: KeyframeStageDeps, result: KeyframeStageResult) -> None:
    _log.info(
        f"{STAGE} complete",
        extra={
            "who": "storygraph.keyframes.stage",
            "where": f"project/{deps.repo.project_id}",
            "what": f"{len(result.rendered)} derived, {len(result.reused)} reused, "
            f"{len(result.manual_edit)} need manual edit, {len(result.failed)} failed",
            "when": datetime.now(UTC).isoformat(),
            "why": "graph-correct 1 fps keyframes are the render inputs",
            "how": "scene queue -> plate -> chained shots/frames -> drift guard -> VLM check",
            "manual_edit_shots": result.manual_edit,
            "failed_shots": result.failed,
        },
    )
