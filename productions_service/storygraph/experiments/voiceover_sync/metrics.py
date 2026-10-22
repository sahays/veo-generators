"""Signal metrics for the voiceover experiment: PCM decode, bed level, median F0, excerpts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import numpy.typing as npt

from ...audio.voice.media import run_ffmpeg
from ...audio.voice.timing import Window

SR = 16_000
FRAME = 640  # 40 ms
F0_MIN, F0_MAX = 70.0, 500.0
VOICED_CORR = 0.45

Signal = npt.NDArray[np.float32]


def decode_pcm(path: Path) -> Signal:
    """Mono 16 kHz float32 samples of a media file's audio."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SR),
        "-f",
        "s16le",
        "-",
    ]
    raw = subprocess.run(
        cmd, capture_output=True, check=True, timeout=120, stdin=subprocess.DEVNULL
    ).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _mask(n: int, windows: list[Window]) -> npt.NDArray[np.bool_]:
    inside = np.zeros(n, dtype=bool)
    for a, b in windows:
        inside[int(a * SR) : int(b * SR)] = True
    return inside


def outside_level_db(x: Signal, windows: list[Window]) -> float | None:
    """RMS level (dBFS) of samples outside every speech window (SFX/ambience bed)."""
    rest = x[~_mask(len(x), windows)]
    if rest.size < SR // 10:
        return None
    return round(float(20 * np.log10(np.sqrt(np.mean(rest**2)) + 1e-9)), 2)


def _frame_f0(frame: Signal) -> float | None:
    frame = frame - frame.mean()
    energy = float(np.dot(frame, frame))
    if energy < 1e-4:
        return None
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1 :] / energy
    lo, hi = int(SR / F0_MAX), int(SR / F0_MIN)
    lag = lo + int(np.argmax(corr[lo:hi]))
    return SR / lag if corr[lag] >= VOICED_CORR else None


def median_f0(x: Signal, window: Window) -> float | None:
    """Median autocorrelation pitch (Hz) over voiced 40 ms frames inside `window`."""
    seg = x[int(window[0] * SR) : int(window[1] * SR)]
    f0s = [
        f
        for i in range(0, len(seg) - FRAME, FRAME)
        if (f := _frame_f0(seg[i : i + FRAME]))
    ]
    return round(float(np.median(f0s)), 1) if len(f0s) >= 3 else None


def cut_excerpt(src: Path, window: Window, out: Path) -> bytes:
    """WAV excerpt of `src` audio within `window` (for audio judgement)."""
    args = ["-ss", f"{window[0]:.3f}", "-to", f"{window[1]:.3f}", "-i", str(src)]
    run_ffmpeg([*args, "-vn", "-ac", "1", "-ar", str(SR), str(out)])
    return out.read_bytes()
