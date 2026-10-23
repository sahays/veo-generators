"""SFX stem sources for `audio.mode=stems` (Omni audio is a guide track only).

`DemucsSfx` (experiment winner, docs/eval/audio_stems_v1.md): htdemucs `no_vocals` of the
guide, frame-synced to picture for free. Residual voice is removed by ducking the stem by
`residual_db` wherever the separated *vocals* stem is active (VAD on vocals, so SFX never
trigger it) or the transcript places speech.

Graph-driven SFX (`graph`/`hybrid`) is not implemented: the Google audio models available
to the project (lyria-002, lyria-3-clip-preview) return music, not discrete foley.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ...schemas.stems import SfxSource
from ..voice.media import MediaTools
from ..voice.separation import DuckRemover, demucs_separate
from ..voice.timing import Window, merge_windows
from ..voice.vad import detect_voice_windows


class SfxStemSource(Protocol):
    @property
    def name(self) -> SfxSource: ...

    def make(self, guide_audio: Path, speech: list[Window], work: Path) -> Path:
        """WAV SFX/ambience stem of `guide_audio` with no audible Omni voice."""
        ...


@dataclass(frozen=True)
class DemucsSfx:
    residual_db: float = -24.0
    model: str = "htdemucs"
    media: MediaTools = field(default_factory=MediaTools)
    name: SfxSource = "demucs"

    def make(self, guide_audio: Path, speech: list[Window], work: Path) -> Path:
        stems = demucs_separate(guide_audio, work, self.model)
        windows = merge_windows([*speech, *detect_voice_windows(stems.vocals)])
        ducked = DuckRemover(self.residual_db, self.media).remove(
            stems.no_vocals, windows, work
        )
        out = work / "sfx_stem.wav"
        ducked.rename(out)
        return out
