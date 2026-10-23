"""Stems stage (`audio.mode: stems`): after QA approval, before S10.

For each ready shot whose winning run has dialogue and no stems yet, Omni's clip is used as
a guide track: lines are re-voiced with each character's fixed voice into a dialogue stem
and the SFX stem is separated from the guide (Omni voice removed). Stems are recorded on
the run (`GenerationRun.stems`, append-only) and mixed in S10 — remixing never re-renders.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from ...assembly import evaluate_shot_readiness
from ...audio.stems import DemucsSfx, StemDeps, build_stems
from ...audio.voice import ensure_cast_voices
from ...config import AudioCfg, Config
from ...errors import StoryGraphError
from ...repo import Repo
from ...schema import GenerationRun, StemSet
from .voiceover_stage import default_sync_deps, speech_lines

logger = logging.getLogger(__name__)
StemDepsFactory = Callable[[AudioCfg], StemDeps]


def default_stem_deps(cfg: AudioCfg) -> StemDeps:
    sync = default_sync_deps(cfg)
    return StemDeps(
        sync=sync, sfx=DemucsSfx(residual_db=cfg.residual_db, media=sync.media)
    )


def _log(level: int, msg: str, what: str, why: str, **fields: object) -> None:
    logger.log(
        level,
        msg,
        extra={
            "who": "storygraph.pipeline",
            "where": "pipeline.stems_stage",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "audio.stems.build_stems on the winning APPROVED run",
            **fields,
        },
    )


def _stem_run(repo: Repo, run: GenerationRun, cfg: AudioCfg, deps: StemDeps) -> bool:
    lines = speech_lines(repo, run.shot_id)
    if not lines or not run.output_video_uri:
        return False
    voices = ensure_cast_voices(repo, {ln.speaker_id for ln in lines}, cfg.tts_model)
    clip = repo.blobs.get_bytes(run.output_video_uri)
    built = build_stems(clip, lines, voices, cfg, deps, shot_ref=run.shot_id)
    base = f"clips/{run.shot_id}_att{run.attempt}_{run.id[-8:]}"
    put = repo.blobs.put_bytes
    stems = StemSet(
        dialogue_uri=put(
            f"{base}_dialogue.flac", built.dialogue, content_type="audio/flac"
        ),
        sfx_uri=put(f"{base}_sfx.flac", built.sfx, content_type="audio/flac"),
        sfx_source=deps.sfx.name,
        duration_s=round(built.duration_s, 3),
        lines=built.lines,
    )
    repo.record_stems(run.id, stems)
    return True


def apply_stems(
    repo: Repo, cfg: Config, deps_factory: StemDepsFactory = default_stem_deps
) -> list[str]:
    """Build stems for every ready shot lacking them; return the run ids that got stems."""
    if cfg.audio.mode != "stems" or cfg.video.provider == "mock":
        return []
    runs = {r.id: r for r in repo.list_generation_runs()}
    pending = [
        runs[s.run_id]
        for s in evaluate_shot_readiness(repo).ready_shots
        if s.run_id in runs and runs[s.run_id].stems is None
    ]
    deps = deps_factory(cfg.audio) if pending else None
    done: list[str] = []
    for run in pending:
        try:
            if deps is not None and _stem_run(repo, run, cfg.audio, deps):
                done.append(run.id)
        except StoryGraphError as exc:
            _log(logging.WARNING, "Stems failed; S10 keeps the Omni clip", "stems_failed",
                 str(exc)[:300], shot_id=run.shot_id, run_id=run.id)  # fmt: skip
    _log(logging.INFO, "Stems stage finished", "stems_stage_done", "audio.mode=stems",
         stem_run_ids=done, pending=len(pending))  # fmt: skip
    return done
