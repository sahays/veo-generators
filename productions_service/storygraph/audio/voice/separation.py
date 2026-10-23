"""Remove Omni's speech from a clip's audio while keeping SFX/ambience.

* `DuckRemover`: attenuate the original mix by `duck_db` inside speech windows with short
  linear ramps (one ffmpeg `volume` expression, evaluated per audio frame).
* `DemucsRemover`: Demucs `htdemucs` two-stem separation (CPU) -> `no_vocals` bed, then a
  light residual duck inside the same windows. Needs the optional demucs/torch runtime
  (`DEMUCS_PYTHON` points at an interpreter that has it).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ...errors import StoryGraphError
from ...schemas.voice import SpeechRemoval
from .media import MediaTools
from .timing import Window

RAMP_S = 0.06
RESIDUAL_DUCK_DB = -6.0
DEMUCS_TIMEOUT_S = 600


class SpeechRemover(Protocol):
    @property
    def name(self) -> SpeechRemoval: ...

    def remove(self, audio_wav: Path, windows: list[Window], work: Path) -> Path: ...


def _window_term(a: float, b: float, ramp: float) -> str:
    """1 inside [a, b], linear ramps of `ramp` s outside, 0 elsewhere."""
    up = f"clip((t-{a - ramp:.3f})/{ramp:.3f},0,1)"
    down = f"clip(({b + ramp:.3f}-t)/{ramp:.3f},0,1)"
    return f"{up}*{down}"


def duck_filter(windows: list[Window], duck_db: float, ramp: float = RAMP_S) -> str:
    """`volume` filter: gain 10^(duck_db/20) inside (merged) windows, 1 elsewhere."""
    if not windows:
        return "anull"
    floor = 10 ** (duck_db / 20.0)
    inside = "+".join(_window_term(a, b, ramp) for a, b in windows)
    return f"volume='1-{1 - floor:.5f}*min(1,{inside})':eval=frame"


@dataclass(frozen=True)
class DuckRemover:
    duck_db: float = -26.0
    media: MediaTools = field(default_factory=MediaTools)
    name: SpeechRemoval = "duck"

    def remove(self, audio_wav: Path, windows: list[Window], work: Path) -> Path:
        out = work / "bed_ducked.wav"
        filt = duck_filter(windows, self.duck_db)
        self.media.run(["-i", str(audio_wav), "-af", filt, str(out)])
        return out


def demucs_python() -> str:
    return os.getenv("DEMUCS_PYTHON", sys.executable)


@dataclass(frozen=True)
class DemucsStems:
    vocals: Path
    no_vocals: Path


def demucs_separate(
    audio_wav: Path, work: Path, model: str = "htdemucs"
) -> DemucsStems:
    """Two-stem (vocals / no_vocals) CPU separation via the demucs CLI."""
    out_dir = work / "demucs"
    cmd = [demucs_python(), "-m", "demucs", "--two-stems", "vocals", "-n", model]
    cmd += ["-d", "cpu", "-o", str(out_dir), str(audio_wav)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=DEMUCS_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoryGraphError(f"demucs failed to start: {exc}") from exc
    base = out_dir / model / audio_wav.stem
    stems = DemucsStems(base / "vocals.wav", base / "no_vocals.wav")
    if proc.returncode != 0 or not stems.no_vocals.is_file():
        tail = proc.stderr.decode(errors="replace")[-400:]
        raise StoryGraphError(f"demucs separation failed: {tail}")
    return stems


@dataclass(frozen=True)
class DemucsRemover:
    model: str = "htdemucs"
    media: MediaTools = field(default_factory=MediaTools)
    name: SpeechRemoval = "demucs"

    def remove(self, audio_wav: Path, windows: list[Window], work: Path) -> Path:
        stems = demucs_separate(audio_wav, work, self.model)
        return DuckRemover(RESIDUAL_DUCK_DB, self.media).remove(
            stems.no_vocals, windows, work
        )


def make_remover(kind: str, duck_db: float, media: MediaTools) -> SpeechRemover:
    """Config -> remover ("demucs" | "duck")."""
    if kind == "demucs":
        return DemucsRemover(media=media)
    return DuckRemover(duck_db=duck_db, media=media)
