"""AV1-decode guard for the detection pipeline (worker image only).

OpenCV (which decodes the frames MediaPipe / cut / text detection consume) can't
HW-decode AV1 in the Cloud Run image and reads 0 frames → no detections → a
static center crop (rf-udcpl2hd). `ensure_cv2_readable` transcodes to H.264 when
cv2 can't read. These tests need ffmpeg (incl. an AV1 encoder) + cv2, so they run
in the worker container and skip on the host venv.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "workers"))

import shutil  # noqa: E402

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")


class _Tmp:
    """Minimal stand-in for the worker's TempFileManager.create(suffix=...)."""

    def __init__(self, tmp_path):
        self._d = tmp_path
        self._n = 0

    def create(self, suffix=""):
        self._n += 1
        p = str(self._d / f"t{self._n}{suffix}")
        return p


def _encode(path, vcodec, dur=1, size="160x120"):
    r = subprocess.run(
        [
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
        ],
        capture_output=True,
    )
    return r.returncode == 0


def _cv2_frames(path):
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


def test_h264_source_passes_through_unchanged(tmp_path):
    pytest.importorskip("cv2")
    from _reframe_helpers import ensure_cv2_readable

    src = tmp_path / "h264.mp4"
    assert _encode(src, "libx264"), "libx264 encode failed"
    out = ensure_cv2_readable(str(src), _Tmp(tmp_path))
    assert out == str(src)  # cv2 can read H.264 → no transcode


def test_av1_source_is_transcoded_to_readable_copy(tmp_path):
    pytest.importorskip("cv2")
    from _reframe_helpers import ensure_cv2_readable

    src = tmp_path / "av1.mp4"
    # libaom-av1 is slow; cpu-used 8 + tiny clip keeps it quick. Some builds lack
    # an AV1 encoder — skip rather than fail in that case.
    ok = (
        subprocess.run(
            [
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
            ],
            capture_output=True,
        ).returncode
        == 0
    )
    if not ok or not src.exists():
        pytest.skip("no AV1 encoder available")

    # If this build's cv2 CAN read AV1, the guard is a no-op and there's nothing
    # to assert; the bug only exists where cv2 reads 0 frames.
    if _cv2_frames(src) > 0:
        pytest.skip("cv2 decodes AV1 in this build — guard not exercised")

    out = ensure_cv2_readable(str(src), _Tmp(tmp_path), "rf-test")
    assert out != str(src)  # transcoded
    assert _cv2_frames(out) > 0  # and now readable by cv2 → MediaPipe gets frames
