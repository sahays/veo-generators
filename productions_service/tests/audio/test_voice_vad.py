"""Speech-band VAD: catches quiet speech-like bursts, bridges short gaps, ignores clicks."""

from __future__ import annotations

import numpy as np
import pytest
from storygraph.audio.voice.vad import SR, voice_windows


def _signal(
    bursts: list[tuple[float, float, float]], total_s: float = 4.0
) -> np.ndarray:
    rng = np.random.default_rng(7)
    x = rng.normal(0.0, 0.0005, int(SR * total_s)).astype(np.float32)  # room-tone floor
    for start, end, amp in bursts:
        a, b = int(start * SR), int(end * SR)
        x[a:b] += rng.normal(0.0, amp, b - a).astype(np.float32)
    return x


def test_whisper_level_burst_is_detected_and_short_gap_bridged() -> None:
    # Loud line 0.5-1.4 s and 1.5-2.0 s (100 ms gap), whisper 2.6-3.2 s ~24 dB quieter.
    x = _signal([(0.5, 1.4, 0.2), (1.5, 2.0, 0.2), (2.6, 3.2, 0.012)])
    wins = voice_windows(x)
    assert len(wins) == 2
    assert wins[0] == (pytest.approx(0.5, abs=0.04), pytest.approx(2.0, abs=0.04))
    assert wins[1] == (pytest.approx(2.6, abs=0.04), pytest.approx(3.2, abs=0.04))


def test_clicks_shorter_than_min_run_are_ignored() -> None:
    x = _signal([(1.0, 1.05, 0.3), (2.0, 2.6, 0.2)])
    assert voice_windows(x) == [
        (pytest.approx(2.0, abs=0.04), pytest.approx(2.6, abs=0.04))
    ]
