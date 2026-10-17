"""AV1-decode guard for the detection pipeline (worker image only).

OpenCV (which decodes the frames MediaPipe / cut / text detection consume) can't
HW-decode AV1 in the Cloud Run image and reads 0 frames → no detections → a
static center crop (rf-udcpl2hd). `ensure_cv2_readable` transcodes to H.264 when
cv2 can't read. These tests need ffmpeg (incl. an AV1 encoder) + cv2, so they run
in the worker container and skip on the host venv.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "workers"))

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")


class _Tmp:
    """Minimal stand-in for the worker's TempFileManager.create(suffix=...)."""

    def __init__(self, tmp_path: Path) -> None:
        self._d = tmp_path
        self._n = 0

    def create(self, suffix: str = "") -> str:
        self._n += 1
        return str(self._d / f"t{self._n}{suffix}")


def _encode(path: Path | str, vcodec: str, dur: int = 1, size: str = "160x120") -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate=25:duration={dur}",
        "-c:v",
        vcodec,
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _encode_av1(src: Path) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x120:rate=25:duration=1",
        "-c:v",
        "libaom-av1",
        "-cpu-used",
        "8",
        "-pix_fmt",
        "yuv420p",
        str(src),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _cv2_frames(path: Path | str) -> int:
    import cv2

    cap = cv2.VideoCapture(str(path))
    n = 0
    while n < 5:
        ok, _ = cap.read()
        if not ok:
            break
        n += 1
    cap.release()
    return n


def test_h264_source_passes_through_unchanged(tmp_path: Any) -> None:
    pytest.importorskip("cv2")
    from _reframe_helpers import ensure_cv2_readable

    src = tmp_path / "h264.mp4"
    assert _encode(src, "libx264"), "libx264 encode failed"
    out = ensure_cv2_readable(str(src), _Tmp(tmp_path))
    assert out == str(src)  # cv2 can read H.264 → no transcode


def test_av1_source_is_transcoded_to_readable_copy(tmp_path: Any) -> None:
    pytest.importorskip("cv2")
    from _reframe_helpers import ensure_cv2_readable

    src = tmp_path / "av1.mp4"
    if not _encode_av1(src) or not src.exists():
        pytest.skip("no AV1 encoder available")
    if _cv2_frames(src) > 0:
        pytest.skip("cv2 decodes AV1 in this build — guard not exercised")

    out = ensure_cv2_readable(str(src), _Tmp(tmp_path), "rf-test")
    assert out != str(src)  # transcoded
    assert _cv2_frames(out) > 0  # and now readable by cv2 → MediaPipe gets frames
