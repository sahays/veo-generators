"""Render one clip's greybox previz and run its restyle variants (failure-isolated).

Reuse key: sha256 of the PrevizScene JSON + the Blender script bytes — an unchanged scene
with a done render is never re-rendered unless forced. Every failure (render or variant) is
stored as a typed reason on the shot record instead of raising.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ...adapters.omni.package import RenderPackage
from ...keyframes.stage.scene_plans import ShotPlan
from ...repo.previz_shots import PrevizShotRepo
from ...schema import Role, Scene, Shot
from ...schemas.previz import (
    PrevizLayout,
    PrevizShot,
    PrevizVariantId,
    PrevizVariantRecord,
)
from ...schemas.previz_scene import PrevizScene
from ..variants.base import base_package
from ..variants.context import PrevizInput
from ..variants.keyframe_restyle import run_e2
from ..variants.omni_restyle import run_e1
from .deps import PrevizStageDeps

_log = logging.getLogger(__name__)
SCRIPT = Path(__file__).resolve().parents[1] / "render" / "build_scene.py"
ISOLATED = (Exception,)  # a shot never takes the run down; the reason is recorded


def scene_hash(scene: PrevizScene) -> str:
    script = SCRIPT.read_bytes() if SCRIPT.is_file() else b""
    body = scene.model_dump_json().encode("utf-8") + hashlib.sha256(script).digest()
    return hashlib.sha256(body).hexdigest()[:16]


@dataclass(frozen=True)
class ShotJob:
    scene: Scene
    plan: ShotPlan
    layout: PrevizLayout
    variants: tuple[PrevizVariantId, ...]
    force: bool


def _draft(job: ShotJob, built: PrevizScene, digest: str) -> PrevizShot:
    shot = job.plan.shot
    return PrevizShot(
        id=f"pzs_{shot.id}",
        created_by=Role.PIPELINE,
        shot_id=shot.id,
        scene_id=shot.scene_id,
        clip_index=shot.clip_index or 0,
        previz_status="running",
        layout_id=job.layout.id,
        scene_hash=digest,
    )


def _render(deps: PrevizStageDeps, ps: PrevizShot, built: PrevizScene) -> PrevizShot:
    shot_id = ps.shot_id
    with tempfile.TemporaryDirectory(dir=deps.workdir) as tmp:
        result = deps.renderer.render(built, Path(tmp))
        if not result.ok or result.mp4_path is None:
            return ps.model_copy(
                update={
                    "previz_status": "failed",
                    "failure_reason": result.failure_text,
                }
            )
        mp4 = result.mp4_path.read_bytes()
    blobs = deps.repo.blobs
    uri = blobs.put_bytes(
        f"previz/{shot_id}/previz_{ps.scene_hash}.mp4", mp4, "video/mp4"
    )
    scene_uri = blobs.put_bytes(
        f"previz/{shot_id}/scene_{ps.scene_hash}.json",
        built.model_dump_json(indent=1).encode("utf-8"),
        "application/json",
    )
    return ps.model_copy(
        update={
            "previz_status": "done",
            "previz_video_uri": uri,
            "scene_json_uri": scene_uri,
            "render_seconds": round(result.seconds, 2),
            "blender_version": result.blender_version,
        }
    )


def ensure_previz(
    deps: PrevizStageDeps, job: ShotJob
) -> tuple[PrevizShot, PrevizScene]:
    """Active record for the clip: reused when current and done, else freshly rendered."""
    sp = job.plan
    built = deps.build_scene(sp.inp, sp.plan, job.layout.layout, job.scene)
    digest = scene_hash(built)
    repo = PrevizShotRepo(deps.repo.store)
    active = repo.active_for_shot(sp.shot.id)
    if active and active.scene_hash == digest and active.previz_status == "done":
        if not job.force:
            return active, built
    ps = repo.create(_draft(job, built, digest))
    try:
        ps = _render(deps, ps, built)
    except ISOLATED as exc:
        ps = ps.model_copy(
            update={"previz_status": "failed", "failure_reason": _reason(exc)}
        )
    _log_shot(deps, ps)
    return repo.put(ps), built


def _reason(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:400]


def _variant(
    deps: PrevizStageDeps, pz: PrevizInput, variant: PrevizVariantId
) -> PrevizVariantRecord:
    vd = deps.variants
    if vd is None:
        return PrevizVariantRecord(
            variant=variant, status="failed", failure_reason="variants not configured"
        )
    try:
        base = (vd.base_for or _production_base(deps))(pz.shot)
        return (
            run_e1(vd, pz, base)
            if variant == "E1_omni_restyle"
            else run_e2(vd, pz, base)
        )
    except ISOLATED as exc:
        return PrevizVariantRecord(
            variant=variant, status="failed", failure_reason=_reason(exc)
        )


def _production_base(deps: PrevizStageDeps) -> Callable[[Shot], RenderPackage]:
    vd = deps.variants
    assert vd is not None
    return lambda shot: base_package(deps.repo, vd.cfg, vd.video_gen.caps, shot)


def run_variants(
    deps: PrevizStageDeps, job: ShotJob, ps: PrevizShot, built: PrevizScene
) -> PrevizShot:
    """Run each requested variant on a done previz; keep other variants' records."""
    if ps.previz_status != "done" or not ps.previz_video_uri or not job.variants:
        return ps
    pz = PrevizInput(
        job.plan.shot,
        job.plan.inp,
        job.plan.plan,
        built,
        ps.previz_video_uri,
        deps.repo.blobs.get_bytes(ps.previz_video_uri),
    )
    records = {v.variant: v for v in ps.variants}
    for variant in job.variants:
        kept = records.get(variant)
        if kept is not None and kept.status == "done" and not job.force:
            continue  # same previz (records live on its version): reuse unless forced
        records[variant] = _variant(deps, pz, variant)
    updated = ps.model_copy(update={"variants": list(records.values())})
    return PrevizShotRepo(deps.repo.store).put(updated)


def _log_shot(deps: PrevizStageDeps, ps: PrevizShot) -> None:
    failed = ps.previz_status == "failed"
    (_log.error if failed else _log.info)(
        "previz shot rendered" if not failed else "previz shot failed",
        extra={
            "who": "storygraph.previz.stage",
            "where": f"{deps.repo.project_id}/{ps.scene_id}/{ps.shot_id}",
            "what": f"previz {ps.previz_status} ({ps.render_seconds or 0:.1f}s render)",
            "when": datetime.now(UTC).isoformat(),
            "why": ps.failure_reason
            or "greybox previz: layout/blocking/camera by construction",
            "how": "PrevizScene -> headless Blender -> MP4 asset",
            "scene_hash": ps.scene_hash,
        },
    )
