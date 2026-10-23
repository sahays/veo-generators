"""Build a clip's stems from Omni's guide track: dialogue (fixed-voice TTS) + SFX."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ...adapters.transcribe import Transcript
from ...config import AudioCfg
from ...schemas.voice import VoicedLine, VoiceProfile
from ..voice.logs import log_ctx
from ..voice.mix import mix_args
from ..voice.sync import SyncDeps, prepare_guide
from ..voice.timing import SpeechLine, speech_windows
from .sfx import SfxStemSource

logger = logging.getLogger(__name__)
STEM_RATE = 48_000


@dataclass(frozen=True)
class StemDeps:
    sync: SyncDeps
    sfx: SfxStemSource


@dataclass(frozen=True)
class BuiltStems:
    dialogue: bytes  # FLAC, clip length, TTS only
    sfx: bytes  # FLAC, clip length, no Omni voice
    duration_s: float
    lines: list[VoicedLine]
    transcript: Transcript


def silence_args(seconds: float, out: Path) -> list[str]:
    src = f"anullsrc=r={STEM_RATE}:cl=stereo"
    return ["-f", "lavfi", "-i", src, "-t", f"{seconds:.3f}", str(out)]


def to_flac_args(src: Path, seconds: float, out: Path) -> list[str]:
    """Clip-length stereo 48 kHz FLAC (padded with silence, trimmed to `seconds`)."""
    return [
        "-i", str(src), "-af", f"apad=whole_dur={seconds:.3f}", "-t", f"{seconds:.3f}",
        "-ar", str(STEM_RATE), "-ac", "2", str(out),
    ]  # fmt: skip


def build_stems(
    clip: bytes,
    lines: list[SpeechLine],
    voices: dict[str, VoiceProfile],
    cfg: AudioCfg,
    deps: StemDeps,
    shot_ref: str = "",
) -> BuiltStems:
    """Guide transcript -> placed TTS dialogue stem + SFX stem (Omni voice never kept)."""
    media = deps.sync.media
    with tempfile.TemporaryDirectory(prefix="stems_") as tmp:
        work = Path(tmp)
        src = work / "clip.mp4"
        src.write_bytes(clip)
        g = prepare_guide(src, lines, voices, cfg, deps.sync)
        silence, dia_wav = work / "silence.wav", work / "dialogue.wav"
        media.run(silence_args(g.clip_s, silence))
        media.run(mix_args(silence, g.line_paths, g.plans, cfg.dialogue_lufs, dia_wav))
        sfx_wav = deps.sfx.make(
            g.orig_audio, speech_windows(g.transcript, g.slots), work
        )
        dia, sfx = work / "dialogue.flac", work / "sfx.flac"
        media.run(to_flac_args(dia_wav, g.clip_s, dia))
        media.run(to_flac_args(sfx_wav, g.clip_s, sfx))
        logger.info(
            "Clip stems built from Omni guide track",
            extra=log_ctx(
                "audio.stems.build",
                "stems_built",
                "audio.mode=stems: final audio is ours, Omni audio is timing guide only",
                f"prepare_guide + TTS dialogue stem + {deps.sfx.name} SFX stem",
                shot_ref=shot_ref,
                line_ids=[ln.line_id for ln in g.lines],
                duration_s=round(g.clip_s, 3),
            ),
        )
        return BuiltStems(
            dia.read_bytes(), sfx.read_bytes(), g.clip_s, g.lines, g.transcript
        )
