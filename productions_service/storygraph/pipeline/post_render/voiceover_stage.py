"""Voiceover sync stage (`audio.voiceover: sync`): runs after QA approval, before S10 stitch.

Dialogue correctness is judged by QA on Omni's original clip; this stage only replaces the
voices. For each ready shot whose winning run has dialogue and no voiced clip yet, the
lines are re-voiced with each character's fixed TTS voice and the new clip is recorded on
the run (`voiced_video_uri`, append-only). Failures keep the original clip (logged).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from ...adapters.gemini_tts import GeminiTTSSynthesizer
from ...adapters.transcribe import GeminiTranscriber
from ...assembly import evaluate_shot_readiness
from ...audio.voice import SpeechLine, SyncDeps, ensure_cast_voices, voice_clip
from ...audio.voice.media import MediaTools
from ...audio.voice.separation import make_remover
from ...config import AudioCfg, Config
from ...errors import StoryGraphError
from ...repo import Repo
from ...schema import GenerationRun, VoiceoverRecord

logger = logging.getLogger(__name__)
DepsFactory = Callable[[AudioCfg], SyncDeps]


def default_sync_deps(cfg: AudioCfg) -> SyncDeps:
    media = MediaTools()
    return SyncDeps(
        transcriber=GeminiTranscriber(),
        synthesizer=GeminiTTSSynthesizer(),
        remover=make_remover(cfg.speech_removal, cfg.duck_db, media),
        media=media,
    )


def _log(level: int, msg: str, what: str, why: str, **fields: object) -> None:
    logger.log(
        level,
        msg,
        extra={
            "who": "storygraph.pipeline",
            "where": "pipeline.voiceover_stage",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "audio.voice.voice_clip on the winning APPROVED run",
            **fields,
        },
    )


def speech_lines(repo: Repo, shot_id: str) -> list[SpeechLine]:
    """Scripted lines of a shot as typed `SpeechLine`s (speaker names resolved)."""
    lines = repo.list_dialogue(shot_id=shot_id)
    names = {e.id: e.canonical_name for e in repo.list_entities()}
    return [
        SpeechLine(
            line_id=ln.id,
            speaker_id=ln.speaker_id,
            speaker_name=names.get(ln.speaker_id, ln.speaker_id),
            lang=ln.language,
            text=ln.text,
            delivery=ln.delivery or "",
        )
        for ln in lines
        if ln.text.strip()
    ]


def _voice_run(repo: Repo, run: GenerationRun, cfg: AudioCfg, deps: SyncDeps) -> bool:
    lines = speech_lines(repo, run.shot_id)
    if not lines or not run.output_video_uri:
        return False
    voices = ensure_cast_voices(repo, {ln.speaker_id for ln in lines}, cfg.tts_model)
    clip = repo.blobs.get_bytes(run.output_video_uri)
    result = voice_clip(clip, lines, voices, cfg, deps, shot_ref=run.shot_id)
    rel = f"clips/{run.shot_id}_att{run.attempt}_{run.id[-8:]}_voiced.mp4"
    uri = repo.blobs.put_bytes(rel, result.video, content_type="video/mp4")
    record = VoiceoverRecord(
        voiced_video_uri=uri,
        speech_removal=deps.remover.name,
        tts_model=cfg.tts_model,
        lines=result.lines,
    )
    repo.record_voiceover(run.id, record)
    return True


def apply_voiceover(
    repo: Repo, cfg: Config, deps_factory: DepsFactory = default_sync_deps
) -> list[str]:
    """Voice every ready shot lacking a voiced clip; return the voiced run ids."""
    if cfg.audio.voiceover != "sync" or cfg.video.provider == "mock":
        return []
    runs = {r.id: r for r in repo.list_generation_runs()}
    pending = [
        runs[s.run_id]
        for s in evaluate_shot_readiness(repo).ready_shots
        if s.run_id in runs and not runs[s.run_id].voiced_video_uri
    ]
    deps = deps_factory(cfg.audio) if pending else None
    voiced: list[str] = []
    for run in pending:
        try:
            if deps is not None and _voice_run(repo, run, cfg.audio, deps):
                voiced.append(run.id)
        except StoryGraphError as exc:
            _log(
                logging.WARNING,
                "Voiceover failed; keeping Omni clip",
                "voiceover_failed",
                str(exc)[:300],
                shot_id=run.shot_id,
                run_id=run.id,
            )
    _log(
        logging.INFO,
        "Voiceover stage finished",
        "voiceover_stage_done",
        "audio.voiceover=sync",
        voiced_run_ids=voiced,
        pending=len(pending),
    )
    return voiced
