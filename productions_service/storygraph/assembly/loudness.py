"""EBU R128 loudness normalization of the stitched master (two-pass ffmpeg `loudnorm`).

Pass 1 measures integrated loudness / true peak / LRA; pass 2 applies a linear gain using
those measurements so the master lands on the target with true peak <= -1 dBTP. Any
ffmpeg failure is logged and the un-normalized master is kept (audio stays valid).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

MasterNormalizer = Callable[[bytes], bytes]
_FFMPEG_TIMEOUT_S: Final[int] = 180
_MIN_VALID_MP4_BYTES: Final[int] = 256
_STDERR_TAIL_CHARS: Final[int] = 2000
_MEASURED_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("measured_I", "input_i"),
    ("measured_TP", "input_tp"),
    ("measured_LRA", "input_lra"),
    ("measured_thresh", "input_thresh"),
    ("offset", "target_offset"),
)


@dataclass(frozen=True)
class LoudnessTarget:
    """EBU R128 programme loudness target."""

    integrated_lufs: float = -23.0
    true_peak_dbtp: float = -1.0
    lra_lu: float = 11.0


EBU_R128: Final[LoudnessTarget] = LoudnessTarget()


def _log_ctx(what: str, why: str, **fields: object) -> dict[str, object]:
    return {
        "who": "storygraph.assembly",
        "where": "assembly.loudness",
        "what": what,
        "why": why,
        "how": "ffmpeg loudnorm two-pass (EBU R128)",
        **fields,
    }


def loudnorm_filter(target: LoudnessTarget, measured: dict[str, str] | None) -> str:
    """`loudnorm` filter string; with `measured` it is the linear second pass."""
    base = (
        f"loudnorm=I={target.integrated_lufs:g}:TP={target.true_peak_dbtp:g}"
        f":LRA={target.lra_lu:g}"
    )
    if measured is None:
        return f"{base}:print_format=json"
    stats = ":".join(f"{opt}={measured[key]}" for opt, key in _MEASURED_KEYS)
    return f"{base}:{stats}:linear=true:print_format=summary"


def parse_loudnorm_json(stderr: str) -> dict[str, str] | None:
    """Extract loudnorm's trailing JSON block from ffmpeg stderr (None when absent)."""
    start, end = stderr.rfind("{"), stderr.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not all(key in data for _, key in _MEASURED_KEYS):
        return None
    return {key: str(data[key]) for _, key in _MEASURED_KEYS}


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stderr.decode("utf-8", errors="replace")


def _measure(src: Path, target: LoudnessTarget) -> dict[str, str] | str:
    """Pass 1: return measured stats or an error string."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src)]
    code, err = _run([*cmd, "-af", loudnorm_filter(target, None), "-f", "null", "-"])
    measured = parse_loudnorm_json(err) if code == 0 else None
    return measured if measured is not None else err[-_STDERR_TAIL_CHARS:]


def _apply(
    src: Path, dst: Path, target: LoudnessTarget, measured: dict[str, str]
) -> str:
    """Pass 2: write the normalized master; return '' on success or the stderr tail."""
    af = loudnorm_filter(target, measured)
    codec = ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd = ["ffmpeg", "-y", "-i", str(src), "-af", af, *codec, "-movflags", "+faststart"]
    code, err = _run([*cmd, str(dst)])
    ok = dst.is_file() and dst.stat().st_size > _MIN_VALID_MP4_BYTES
    return "" if code == 0 and ok else (err[-_STDERR_TAIL_CHARS:] or f"exit {code}")


def _normalize_in(tmp: Path, video: bytes, target: LoudnessTarget) -> bytes | str:
    src, dst = tmp / "master.mp4", tmp / "master_r128.mp4"
    src.write_bytes(video)
    measured = _measure(src, target)
    if isinstance(measured, str):
        return f"measure pass failed: {measured}"
    err = _apply(src, dst, target, measured)
    return dst.read_bytes() if not err else f"apply pass failed: {err}"


def ffmpeg_loudnorm(video: bytes, target: LoudnessTarget = EBU_R128) -> bytes:
    """Normalize the master's audio to `target`; keep `video` unchanged on any failure."""
    if shutil.which("ffmpeg") is None:
        logger.error(
            "ffmpeg missing; master left un-normalized",
            extra=_log_ctx("loudnorm_unavailable", "ffmpeg not on PATH"),
        )
        return video
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _normalize_in(Path(tmpdir), video, target)
    if isinstance(result, bytes):
        logger.info(
            "Master loudness normalized",
            extra=_log_ctx(
                "loudnorm_applied", "EBU R128 delivery spec", target=str(target)
            ),
        )
        return result
    logger.error(
        "Loudness normalization failed; master left un-normalized",
        extra=_log_ctx(
            "loudnorm_failed", "ffmpeg returned an error", stderr_tail=result
        ),
    )
    return video


def select_normalizer(video_provider: str) -> MasterNormalizer | None:
    """EBU R128 normalizer for real providers; mock clips are synthetic bytes."""
    return None if video_provider == "mock" else ffmpeg_loudnorm
