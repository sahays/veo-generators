"""Voiceover sync for one rendered clip: transcribe -> TTS -> time-fit -> remove speech -> mix.

Contracts are typed and injected (`SyncDeps`) so the pipeline, the experiment and tests
share one implementation. The original clip bytes are never modified.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ...adapters.transcribe import Transcriber, Transcript
from ...config import AudioCfg
from ...schemas.voice import VoicedLine, VoiceProfile
from .logs import log_ctx
from .media import MediaTools, extract_audio_args, mux_args, trim_silence_args
from .mix import mix_args
from .separation import SpeechRemover
from .timefit import FitPlan, place_lines
from .timing import LineSlot, SpeechLine, Window, line_slots, speech_windows
from .vad import detect_voice_windows

logger = logging.getLogger(__name__)


class LineSynthesizer(Protocol):
    def synthesize(
        self, text: str, voice: VoiceProfile, lang: str, target_s: float | None
    ) -> bytes:
        """WAV bytes of `text` in the fixed `voice`, paced toward `target_s` seconds."""
        ...


@dataclass(frozen=True)
class SyncDeps:
    transcriber: Transcriber
    synthesizer: LineSynthesizer
    remover: SpeechRemover
    media: MediaTools = field(default_factory=MediaTools)
    vad: Callable[[Path], list[Window]] = detect_voice_windows


@dataclass(frozen=True)
class VoicedClip:
    video: bytes
    lines: list[VoicedLine]
    transcript: Transcript
    speech_removal: str


def _synth_lines(
    slots: list[LineSlot],
    voices: dict[str, VoiceProfile],
    deps: SyncDeps,
    work: Path,
    pace_factor: float,
) -> tuple[list[Path], list[float]]:
    """Synthesize + edge-trim each line; return trimmed paths and their durations."""
    paths: list[Path] = []
    lengths: list[float] = []
    for i, slot in enumerate(slots):
        ln = slot.line
        raw = work / f"line_{i}_raw.wav"
        raw.write_bytes(
            deps.synthesizer.synthesize(
                ln.text,
                voices[ln.speaker_id],
                ln.lang,
                (slot.end - slot.start) * pace_factor,
            )
        )
        trimmed = work / f"line_{i}.wav"
        deps.media.run(trim_silence_args(raw, trimmed))
        paths.append(trimmed)
        lengths.append(deps.media.probe(trimmed))
    return paths, lengths


def _voiced_lines(
    slots: list[LineSlot], plans: list[FitPlan], voices: dict[str, VoiceProfile]
) -> list[VoicedLine]:
    return [
        VoicedLine(
            line_id=s.line.line_id,
            speaker_id=s.line.speaker_id,
            voice_name=voices[s.line.speaker_id].voice_name,
            slot_start_s=round(s.start, 3),
            slot_end_s=round(s.end, 3),
            placed_start_s=round(p.start, 3),
            placed_end_s=round(p.end, 3),
            tempo=p.tempo,
            estimated_slot=s.estimated,
            overrun_s=round(p.overrun_s, 3),
        )
        for s, p in zip(slots, plans, strict=True)
    ]


def _log_result(shot_ref: str, lines: list[VoicedLine], remover: str) -> None:
    overruns = [ln.line_id for ln in lines if ln.overrun_s > 0]
    logger.log(
        logging.WARNING if overruns else logging.INFO,
        "Clip voiced with fixed character voices",
        extra=log_ctx(
            "audio.voice.sync",
            "clip_voiced",
            "voiceover sync keeps each character's voice identical across clips",
            f"transcript-aligned TTS, atempo fit, {remover} speech removal, amix",
            shot_ref=shot_ref,
            line_ids=[ln.line_id for ln in lines],
            estimated_line_ids=[ln.line_id for ln in lines if ln.estimated_slot],
            overrun_line_ids=overruns,
        ),
    )


def voice_clip(
    clip: bytes,
    lines: list[SpeechLine],
    voices: dict[str, VoiceProfile],
    cfg: AudioCfg,
    deps: SyncDeps,
    shot_ref: str = "",
) -> VoicedClip:
    """Return a new clip whose dialogue is re-voiced; SFX/ambience bed kept."""
    with tempfile.TemporaryDirectory(prefix="voiceover_") as tmp:
        work = Path(tmp)
        src = work / "clip.mp4"
        src.write_bytes(clip)
        clip_s = deps.media.probe(src)
        names = sorted({ln.speaker_name for ln in lines})
        transcript = deps.transcriber.transcribe(
            clip, names, sorted({ln.lang for ln in lines})
        )
        slots = line_slots(lines, transcript, clip_s)
        paths, lengths = _synth_lines(slots, voices, deps, work, cfg.pace_factor)
        plans = place_lines(slots, lengths, clip_s, (cfg.tempo_min, cfg.tempo_max))
        orig = work / "orig.wav"
        deps.media.run(extract_audio_args(src, orig))
        windows = speech_windows(transcript, slots, deps.vad(orig))
        bed = deps.remover.remove(orig, windows, work)
        mixed, out = work / "mixed.wav", work / "voiced.mp4"
        deps.media.run(mix_args(bed, paths, plans, cfg.voice_lufs, mixed))
        deps.media.run(mux_args(src, mixed, out, clip_s))
        voiced = _voiced_lines(slots, plans, voices)
        _log_result(shot_ref, voiced, deps.remover.name)
        return VoicedClip(out.read_bytes(), voiced, transcript, deps.remover.name)
