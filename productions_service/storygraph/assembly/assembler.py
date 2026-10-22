"""Final Video Assembly (`S10_ASSEMBLE`): stitch APPROVED shot clips into a master MP4.

Strict mode (default) refuses to stitch while any shot is blocking. Partial mode
(`allow_partial=True`, the manual "stitch approved shots only" action) stitches the
APPROVED shots in story order and records the skipped shots on `ProjectMeta`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..config import AssemblyCfg
from ..errors import ShotsNotApproved, ValidationFailed
from ..repo import Repo
from .loudness import MasterNormalizer
from .music import MusicMixer, apply_music_bed
from .music_ffmpeg import ffprobe_duration
from .readiness import AssemblyReadiness, evaluate_shot_readiness
from .stitch import ClipStitcher, ffmpeg_stitch
from .timing import DurationProbe, measure_clip_timings

logger = logging.getLogger(__name__)

STATUS_COMPLETED = "completed"
STATUS_COMPLETED_PARTIAL = "completed_partial"
PARTIAL_NOTE_PREFIX = "Partial assembly: skipped unapproved shots "


def _log_ctx(
    what: str, why: str, project_id: str, **fields: object
) -> dict[str, object]:
    return {
        "who": "storygraph.assembly",
        "where": "assembly.assemble",
        "what": what,
        "why": why,
        "how": "evaluate_shot_readiness + stitcher",
        "project_id": project_id,
        "when": datetime.now(UTC).isoformat(),
        **fields,
    }


def _project_id(repo: Repo) -> str:
    meta = repo.get_project_meta()
    return meta.id if meta else ""


def _guard_readiness(
    repo: Repo, readiness: AssemblyReadiness, allow_partial: bool
) -> None:
    """Raise `ShotsNotApproved` when the requested mode cannot proceed."""
    blocked = readiness.blocking_reasons()
    if not allow_partial and blocked:
        logger.warning(
            "Strict assembly blocked by unapproved shots",
            extra=_log_ctx(
                "assembly_blocked",
                "shots lack an APPROVED clip",
                _project_id(repo),
                blocking_shot_ids=list(blocked),
                mode="strict",
            ),
        )
        raise ShotsNotApproved(blocked, context="S10_ASSEMBLE")
    if not readiness.ready_shots:
        logger.warning(
            "Partial assembly has zero approved shots",
            extra=_log_ctx(
                "assembly_blocked",
                "no APPROVED clips exist",
                _project_id(repo),
                blocking_shot_ids=list(blocked),
                mode="approved_only",
            ),
        )
        raise ShotsNotApproved(
            blocked, context="S10_ASSEMBLE (approved_only, zero approved)"
        )


def _record_final_video(
    repo: Repo, final_uri: str, readiness: AssemblyReadiness
) -> None:
    meta = repo.get_project_meta()
    if meta is None:
        return
    skipped = [b.shot_id for b in readiness.blocking]
    sign = getattr(repo.blobs, "sign_url", None)
    repo.put_project_meta(
        meta.model_copy(
            update={
                "final_video_uri": final_uri,
                "final_video_url": sign(final_uri) if callable(sign) else final_uri,
                "status": STATUS_COMPLETED_PARTIAL if skipped else STATUS_COMPLETED,
                "current_stage": "S10_ASSEMBLE",
                "skipped_shot_ids": skipped,
                "error_message": PARTIAL_NOTE_PREFIX + ", ".join(skipped)
                if skipped
                else None,
                "updated_at": datetime.now(UTC),
            }
        )
    )


def assemble(
    repo: Repo,
    out_rel_path: str = "out/final.mp4",
    allow_partial: bool = False,
    stitcher: ClipStitcher | None = None,
    music_mixer: MusicMixer | None = None,
    assembly_cfg: AssemblyCfg | None = None,
    duration_probe: DurationProbe = ffprobe_duration,
    normalizer: MasterNormalizer | None = None,
    prefer_voiced: bool = False,
) -> str:
    """Stitch the winning APPROVED clip of each shot in story order and return the blob URI.

    After stitching, scene `MusicCue` audio (if any) is mixed under the result by
    `music_mixer` using each clip's probed duration; with no music assets or no mixer the
    stitched video is kept as-is. Finally `normalizer` (EBU R128 loudnorm) runs on the master.
    `prefer_voiced` stitches each run's voiceover-synced clip when present (`audio.voiceover`).
    """
    readiness = evaluate_shot_readiness(repo, prefer_voiced=prefer_voiced)
    if not readiness.ready_shots and not readiness.blocking:
        raise ValidationFailed(["Cannot assemble final video: no shots exist"])
    _guard_readiness(repo, readiness, allow_partial)
    clips = [repo.blobs.get_bytes(r.video_uri) for r in readiness.ready_shots]
    timings = measure_clip_timings(repo, readiness.ready_shots, clips, duration_probe)
    merged = apply_music_bed(
        repo,
        readiness.ready_shots,
        [t.actual_s for t in timings],
        (stitcher or ffmpeg_stitch)(clips),
        assembly_cfg or AssemblyCfg(),
        music_mixer,
    )
    if normalizer is not None:
        merged = normalizer(merged)
    final_uri = repo.blobs.put_bytes(out_rel_path, merged, content_type="video/mp4")
    _record_final_video(repo, final_uri, readiness)
    logger.info(
        "Final video assembled",
        extra=_log_ctx(
            "assembly_completed",
            "S10 stitch requested",
            _project_id(repo),
            mode="approved_only" if allow_partial else "strict",
            stitched_shot_ids=[r.shot_id for r in readiness.ready_shots],
            skipped_shot_ids=[b.shot_id for b in readiness.blocking],
            final_uri=final_uri,
        ),
    )
    return final_uri
