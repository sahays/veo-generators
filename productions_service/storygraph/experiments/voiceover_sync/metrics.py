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


MAX_LAG_S = 0.2


def bed_lag_ms(orig: Signal, voiced: Signal, windows: list[Window]) -> float | None:
    """Lag (ms) maximizing cross-correlation of the two beds outside speech (FFT, O(n log n)).

    0 means the SFX bed is sample-aligned with the original picture-synced audio.
    """
    n = min(len(orig), len(voiced))
    keep = ~_mask(n, windows)
    a, b = orig[:n] * keep, voiced[:n] * keep
    if float(np.dot(a, a)) < 1e-6 or float(np.dot(b, b)) < 1e-6:
        return None
    size = 1 << (2 * n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    max_lag = int(MAX_LAG_S * SR)
    lags = np.concatenate((corr[: max_lag + 1], corr[-max_lag:]))
    idx = int(np.argmax(lags))
    lag = idx if idx <= max_lag else idx - len(lags)
    return round(1000.0 * lag / SR, 1)
