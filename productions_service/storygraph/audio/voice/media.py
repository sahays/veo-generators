"""ffmpeg/ffprobe operations for voiceover sync behind an injectable `MediaTools` contract."""

from __future__ import annotations

import io
import subprocess
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ...errors import StoryGraphError

SAMPLE_RATE = 48_000
FFMPEG_TIMEOUT_S = 300
# Strip leading/trailing silence (< -45 dB) and cap inner pauses at 0.3 s (TTS often
# leaves long dramatic pauses that force tempo to its bound). Voiced audio is untouched.
_TRIM_EDGE = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02"
_CAP_PAUSES = "silenceremove=stop_periods=-1:stop_duration=0.3:stop_threshold=-45dB:stop_silence=0.3"
TRIM_SILENCE_FILTER = f"{_TRIM_EDGE},{_CAP_PAUSES},areverse,{_TRIM_EDGE},areverse"

Runner = Callable[[list[str]], None]
Probe = Callable[[Path], float]


def run_ffmpeg(args: list[str]) -> None:
    """Run `ffmpeg -y <args>`; raise `StoryGraphError` with stderr tail on failure."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoryGraphError(f"ffmpeg failed to start: {exc}") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace")[-400:]
        raise StoryGraphError(f"ffmpeg exited {proc.returncode}: {tail}")


def probe_duration(path: Path) -> float:
    """Media duration in seconds via ffprobe."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration"]
    try:
        proc = subprocess.run(
            [*cmd, "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        return float(proc.stdout.decode().strip())
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise StoryGraphError(
            f"ffprobe could not read duration of {path.name}"
        ) from exc


@dataclass(frozen=True)
class MediaTools:
    """Injectable media seam (tests pass fakes; production uses ffmpeg/ffprobe)."""

    run: Runner = run_ffmpeg
    probe: Probe = probe_duration


def pcm_to_wav(pcm: bytes, rate: int = 24_000, channels: int = 1) -> bytes:
    """Wrap raw little-endian 16-bit PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def extract_audio_args(clip: Path, out_wav: Path) -> list[str]:
    return ["-i", str(clip), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), str(out_wav)]


def trim_silence_args(in_wav: Path, out_wav: Path) -> list[str]:
    return [
        "-i",
        str(in_wav),
        "-af",
        TRIM_SILENCE_FILTER,
        "-ar",
        str(SAMPLE_RATE),
        str(out_wav),
    ]


def mux_args(clip: Path, audio: Path, out_mp4: Path, clip_s: float) -> list[str]:
    """Replace the clip's audio track; video stream copied bit-exact, length kept."""
    return [
        "-i",
        str(clip),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{clip_s:.3f}",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
