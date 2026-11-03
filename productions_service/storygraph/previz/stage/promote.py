"""Promote a previz variant output to the shot's active render (S9 QA / S10 use it).

Creates a normal, append-only `GenerationRun` (provider `previz_<variant>`, status RENDERED,
current shot content hash, next attempt number) pointing at the variant MP4, so the latest
run of the shot is the promoted clip; S9 QA then judges it like any other render. Exactly one
variant of a shot is marked `promoted`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ...errors import NotFound, ValidationFailed
from ...repo import Repo
from ...repo.previz_shots import PrevizShotRepo
from ...schema import GenerationRun, Role, Status
from ...schemas.previz import PrevizShot, PrevizVariantId, PrevizVariantRecord

_log = logging.getLogger(__name__)


def _promotable(ps: PrevizShot | None, variant: PrevizVariantId) -> PrevizVariantRecord:
    if ps is None:
        raise NotFound("no previz for this shot: run S8_PREVIZ first")
    rec = next((v for v in ps.variants if v.variant == variant), None)
    if rec is None or rec.status != "done" or not rec.video_uri:
        raise ValidationFailed([f"{variant} has no finished output to promote"])
    return rec


def _run(repo: Repo, ps: PrevizShot, rec: PrevizVariantRecord) -> GenerationRun:
    shot = repo.get_shot(ps.shot_id)
    if shot is None:
        raise NotFound(f"shot {ps.shot_id} not found")
    attempt = (
        max((r.attempt for r in repo.list_generation_runs(shot_id=shot.id)), default=0)
        + 1
    )
    return GenerationRun(
        id=f"run_{shot.id}_att{attempt}_previz_{rec.variant.split('_')[0].lower()}",
        created_by=Role.PIPELINE,
        status=Status.RENDERED,
        shot_id=shot.id,
        attempt=attempt,
        provider=f"previz_{rec.variant}",
        model=rec.model or rec.variant,
        compiled_prompt=rec.prompt,
        seed=0,
        package_hash=ps.scene_hash or ps.id,
        output_video_uri=rec.video_uri,
        shot_content_hash=shot.content_hash,
    )


def promote_variant(repo: Repo, shot_id: str, variant: PrevizVariantId) -> PrevizShot:
    shots = PrevizShotRepo(repo.store)
    ps = shots.active_for_shot(shot_id)
    rec = _promotable(ps, variant)
    assert ps is not None  # _promotable raised otherwise
    run = repo.add_generation_run(_run(repo, ps, rec))
    variants = [
        v.model_copy(
            update={
                "promoted": v.variant == variant,
                "generation_run_id": run.id
                if v.variant == variant
                else v.generation_run_id,
            }
        )
        for v in ps.variants
    ]
    updated = shots.put(ps.model_copy(update={"variants": variants}))
    _log.info(
        "previz variant promoted",
        extra={
            "who": "storygraph.previz.promote",
            "where": f"{repo.project_id}/{shot_id}",
            "what": f"{variant} -> GenerationRun {run.id} (attempt {run.attempt})",
            "when": datetime.now(UTC).isoformat(),
            "why": "human picked a previz variant as the shot's render",
            "how": "append-only GenerationRun, status RENDERED for S9 QA",
        },
    )
    return updated
