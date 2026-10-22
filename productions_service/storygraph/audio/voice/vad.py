"""Speech-band energy VAD over a clip's original audio (finds Omni speech the transcript misses).

Whispers are unvoiced, so pitch-based VAD misses them; this detector uses 200–3800 Hz band
energy against an adaptive floor: active when a 30 ms frame is >= `FLOOR_MARGIN_DB` above the
20th-percentile floor and within `PEAK_RANGE_DB` of the loudest frame. Gaps shorter than
`MAX_GAP_S` are bridged, bursts shorter than `MIN_RUN_S` dropped. O(n) over samples.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import numpy.typing as npt

from ...errors import StoryGraphError
from .timing import Window

SR = 16_000
FRAME_S = 0.03
FLOOR_PERCENTILE = 20
FLOOR_MARGIN_DB = 10.0
PEAK_RANGE_DB = 30.0
MAX_GAP_S = 0.2
MIN_RUN_S = 0.12

Samples = npt.NDArray[np.float32]


def read_speech_band(path: Path) -> Samples:
    """Mono 16 kHz float samples of `path` band-limited to the speech band."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
        "-af", "highpass=f=200,lowpass=f=3800", "-f", "s16le", "-",
    ]  # fmt: skip
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=120, check=True, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoryGraphError(f"VAD could not decode {path.name}: {exc}") from exc
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _frame_db(x: Samples) -> npt.NDArray[np.float64]:
    n = int(SR * FRAME_S)
    frames = x[: len(x) // n * n].reshape(-1, n).astype(np.float64)
    return 10.0 * np.log10(np.mean(frames**2, axis=1) + 1e-10)


def _runs(active: npt.NDArray[np.bool_]) -> list[Window]:
    """Contiguous active frame runs as (start_s, end_s)."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], active.astype(np.int8), [0]))))
    return [
        (s * FRAME_S, e * FRAME_S) for s, e in zip(edges[::2], edges[1::2], strict=True)
    ]


def voice_windows(x: Samples) -> list[Window]:
    """Speech-band activity windows (seconds), gap-bridged and burst-filtered."""
    db = _frame_db(x)
    if db.size == 0:
        return []
    threshold = max(
        np.percentile(db, FLOOR_PERCENTILE) + FLOOR_MARGIN_DB, db.max() - PEAK_RANGE_DB
    )
    bridged: list[Window] = []
    for a, b in _runs(db >= threshold):
        if bridged and a - bridged[-1][1] < MAX_GAP_S:
            bridged[-1] = (bridged[-1][0], b)
        else:
            bridged.append((a, b))
    return [
        (round(float(a), 3), round(float(b), 3))
        for a, b in bridged
        if b - a >= MIN_RUN_S
    ]


def detect_voice_windows(audio: Path) -> list[Window]:
    """Production VAD seam: decode + detect."""
    return voice_windows(read_speech_band(audio))
