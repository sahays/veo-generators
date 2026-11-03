"""Run S8_PREVIZ for a project: scenes in parallel, clips per scene, variants per clip.

Outside the main cascade: it never marks shots stale and never touches GenerationRuns
(promote does that explicitly). Progress lives on a `PrevizRun` (live status for the UI) and
an append-only `StageRun` is recorded when the run ends. A scene whose layout or plans fail
marks its clips failed with the reason; other scenes continue.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...keyframes.plan.sampling.models import DENSE
from ...keyframes.stage.scene_plans import stored_scene_plans
from ...repo.previz_shots import PrevizRunRepo, PrevizShotRepo
from ...schema import Role, Scene, StageRun, Status
from ...schemas.previz import PrevizRun, PrevizRunVariant, PrevizShot, PrevizVariantId
from .deps import STAGE_ID, PrevizStageDeps
from .shot import ShotJob, ensure_previz, run_variants

_log = logging.getLogger(__name__)
VARIANTS_OF: dict[str, tuple[PrevizVariantId, ...]] = {
    "previz_only": (),
    "E1_omni_restyle": ("E1_omni_restyle",),
    "E2_keyframe_restyle": ("E2_keyframe_restyle",),
    "both": ("E1_omni_restyle", "E2_keyframe_restyle"),
}


@dataclass
class PrevizTally:
    done: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    def merge(self, other: PrevizTally) -> None:
        self.done += other.done
        self.failed |= other.failed

    def add(self, ps: PrevizShot) -> None:
        if ps.previz_status == "done":
            self.done.append(ps.shot_id)
        else:
            self.failed[ps.shot_id] = ps.failure_reason or "unknown failure"


def _shot(deps: PrevizStageDeps, job: ShotJob) -> PrevizShot:
    ps, built = ensure_previz(deps, job)
    return run_variants(deps, job, ps, built)


def _fail_scene(deps: PrevizStageDeps, scene: Scene, reason: str) -> PrevizTally:
    repo, tally = PrevizShotRepo(deps.repo.store), PrevizTally()
    for shot in deps.repo.list_shots(scene_id=scene.id):
        if shot.clip_index is None:
            continue
        ps = PrevizShot(
            id=f"pzs_{shot.id}",
            created_by=Role.PIPELINE,
            shot_id=shot.id,
            scene_id=scene.id,
            clip_index=shot.clip_index,
            previz_status="failed",
            failure_reason=reason,
        )
        tally.add(repo.create(ps))
    return tally


def run_scene(
    deps: PrevizStageDeps, scene: Scene, variant: PrevizRunVariant, force: bool
) -> PrevizTally:
    try:
        layout = deps.layouts(scene)
        plans = list(stored_scene_plans(deps.repo, scene, sampling=DENSE).values())
    except Exception as exc:  # scene-level isolation: record + continue other scenes
        return _fail_scene(deps, scene, f"{type(exc).__name__}: {exc}"[:400])
    jobs = [ShotJob(scene, sp, layout, VARIANTS_OF[variant], force) for sp in plans]
    tally = PrevizTally()
    with ThreadPoolExecutor(max_workers=max(1, deps.shot_workers)) as pool:
        for ps in pool.map(lambda j: _shot(deps, j), jobs):
            tally.add(ps)
    return tally


def _selected(deps: PrevizStageDeps, scene_ids: list[str] | None) -> list[Scene]:
    scenes = deps.repo.list_scenes()
    return [s for s in scenes if scene_ids is None or s.id in scene_ids]


def _stage_run(
    run: PrevizRun, suffix: str, status: Status, error: str | None
) -> StageRun:
    """Append-only StageRun rows: `<run>_start` while running, `<run>` when it ends."""
    return StageRun(
        id=f"sr_{STAGE_ID}_{run.id}{suffix}",
        created_by=Role.PIPELINE,
        status=status,
        stage=STAGE_ID,
        input_hash=f"{run.variant}:{','.join(run.scene_ids or ['*'])}",
        completed=status == Status.APPROVED,
        error=error,
    )


def _finish(
    deps: PrevizStageDeps, run: PrevizRun, tally: PrevizTally, error: str | None
) -> PrevizRun:
    failed = error is not None or (bool(tally.failed) and not tally.done)
    done = run.model_copy(
        update={
            "run_status": "failed" if failed else "approved",
            "finished_at": datetime.now(UTC).isoformat(),
            "error": error
            or ("; ".join(sorted(set(tally.failed.values())))[:400] or None),
            "shots_done": len(tally.done),
            "shots_failed": len(tally.failed),
        }
    )
    status = Status.FAILED if failed else Status.APPROVED
    deps.repo.record_stage_run(_stage_run(run, "", status, done.error))
    return PrevizRunRepo(deps.repo.store).put(done)


def run_previz(deps: PrevizStageDeps, run: PrevizRun) -> PrevizRun:
    """Execute `run` (already stored as running); returns the final run record."""
    tally, error = PrevizTally(), None
    deps.repo.record_stage_run(_stage_run(run, "_start", Status.PROPOSED, None))
    try:
        scenes = _selected(deps, run.scene_ids)
        workers = max(1, min(deps.scene_workers, len(scenes) or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            parts = pool.map(
                lambda s: run_scene(deps, s, run.variant, run.force), scenes
            )
            for part in parts:
                tally.merge(part)
    except Exception as exc:  # the run record must always be closed
        error = f"{type(exc).__name__}: {exc}"[:400]
    final = _finish(deps, run, tally, error)
    _log_run(deps, final, tally)
    return final


def _log_run(deps: PrevizStageDeps, run: PrevizRun, tally: PrevizTally) -> None:
    _log.info(
        "S8_PREVIZ complete",
        extra={
            "who": "storygraph.previz.stage",
            "where": f"project/{deps.repo.project_id}/{run.id}",
            "what": f"{len(tally.done)} previz done, {len(tally.failed)} failed",
            "when": datetime.now(UTC).isoformat(),
            "why": f"previz request variant={run.variant} scenes={run.scene_ids or 'all'}",
            "how": "layout -> blocking -> Blender greybox -> restyle variants",
            "failed_shots": tally.failed,
            "status": run.run_status,
        },
    )
