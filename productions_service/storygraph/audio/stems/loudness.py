"""Stem loudness: EBU R128 integrated loudness measurement + bounded gain math."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

SILENCE_LUFS: Final[
    float
] = -70.0  # ebur128 gate floor; quieter stems are treated as silent
_INTEGRATED_RE: Final[re.Pattern[str]] = re.compile(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS")


def measure_lufs(path: Path) -> float | None:
    """Integrated loudness (LUFS) of `path` via ffmpeg `ebur128`, None when unmeasurable."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path)]
    cmd += ["-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=120, check=False, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = _INTEGRATED_RE.findall(proc.stderr.decode(errors="replace"))
    return float(found[-1]) if found else None


def loudness_gain_db(
    measured: float | None,
    target: float,
    max_boost_db: float,
    user_gain_db: float = 0.0,
) -> float:
    """Gain (dB) bringing `measured` to `target`, boost capped, plus the user trim.

    Silent/unmeasurable stems get only the user trim (never boost room noise to target).
    Attenuation is uncapped so a loud stem always lands at or below its target.
    """
    if measured is None or measured <= SILENCE_LUFS:
        return round(user_gain_db, 2)
    return round(min(target - measured, max_boost_db) + user_gain_db, 2)


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20.0)
