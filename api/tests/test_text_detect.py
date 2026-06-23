"""Unit tests for the wide-text detector (reframe v2 Phase 2)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from text_detect import detect_text_coverage, scan_video_text  # noqa: E402

W, H = 1920, 1080


def _blank():
    return np.zeros((H, W, 3), dtype=np.uint8)


def _wide_text_frame(text="BREAKING NEWS HEADLINE TODAY", x0=80):
    """A dark frame with one wide white text line — a title card / lower-third."""
    img = _blank()
    cv2.putText(
        img, text, (x0, H // 2), cv2.FONT_HERSHEY_SIMPLEX, 4.0, (255, 255, 255), 8
    )
    return img


class TestDetectTextCoverage:
    def test_blank_frame_has_no_text(self):
        cov, span = detect_text_coverage(_blank())
        assert cov == 0.0
        assert span == (0.0, 0.0)

    def test_wide_text_detected(self):
        cov, (x0, x1) = detect_text_coverage(_wide_text_frame())
        assert cov >= 0.3  # a near-full-width headline
        assert x1 > x0
        assert x0 < 0.5 < x1  # spans the center

    def test_solid_bar_is_not_text(self):
        # A filled white rectangle (e.g. a colour bar) must not read as text:
        # its interior has no strokes, so the edge map is near-empty inside.
        img = _blank()
        cv2.rectangle(img, (80, 500), (W - 80, 560), (255, 255, 255), -1)
        cov, _ = detect_text_coverage(img)
        assert cov == 0.0

    def test_tiny_frame_skipped(self):
        cov, span = detect_text_coverage(np.zeros((16, 16, 3), dtype=np.uint8))
        assert cov == 0.0

    def test_none_frame_safe(self):
        assert detect_text_coverage(None) == (0.0, (0.0, 0.0))


class TestScanVideoText:
    def test_missing_file_degrades_to_empty(self):
        assert scan_video_text("/no/such/video.mp4") == []
