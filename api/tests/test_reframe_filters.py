"""Unit tests for reframe filter generation — aspect ratios and crop math."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_filters import (
    build_crop_filter,
    build_blurred_bg_filter,
    build_vertical_split_filter,
    _to_pixel_keypoints,
)

CENTER = [(0.0, 0.5, 0.5), (10.0, 0.5, 0.5)]


# ---------------------------------------------------------------------------
# 9:16 crop filter
# ---------------------------------------------------------------------------


class TestCropFilter:
    def test_1920x1080_dimensions(self):
        f = build_crop_filter(CENTER, 1920, 1080)
        assert "crop=607:1080" in f
        assert "scale=1080:1920" in f

    def test_1280x720_dimensions(self):
        f = build_crop_filter(CENTER, 1280, 720)
        assert "crop=405:720" in f
        assert "scale=1080:1920" in f

    def test_640x360_dimensions(self):
        f = build_crop_filter(CENTER, 640, 360)
        assert "crop=202:360" in f
        assert "scale=1080:1920" in f

    def test_3840x2160_dimensions(self):
        f = build_crop_filter(CENTER, 3840, 2160)
        assert "crop=1215:2160" in f
        assert "scale=1080:1920" in f

    def test_narrow_source_just_scales(self):
        """Source narrower than 9:16 — no crop, just scale."""
        f = build_crop_filter(CENTER, 360, 640)
        assert f == "scale=1080:1920"

    def test_empty_keypoints_centers(self):
        f = build_crop_filter([], 1920, 1080)
        assert "crop=607:1080" in f
        assert "scale=1080:1920" in f

    def test_single_keypoint(self):
        f = build_crop_filter([(5.0, 0.3, 0.5)], 1920, 1080)
        assert "crop=607:1080" in f

    def test_dynamic_pan_has_clip(self):
        kps = [(0.0, 0.2, 0.5), (5.0, 0.8, 0.5)]
        f = build_crop_filter(kps, 1920, 1080)
        assert "clip(" in f
        assert "if(lt(t" in f


# ---------------------------------------------------------------------------
# 4:5 blurred background filter
# ---------------------------------------------------------------------------


class TestBlurredBgFilter:
    def test_1920x1080_dimensions(self):
        f = build_blurred_bg_filter(CENTER, 1920, 1080)
        assert "1080:1350" in f
        assert "crop=864:1080" in f
        assert "gblur=sigma=40" in f
        assert "overlay" in f

    def test_1280x720_dimensions(self):
        f = build_blurred_bg_filter(CENTER, 1280, 720)
        assert "1080:1350" in f
        assert "crop=576:720" in f

    def test_640x360_dimensions(self):
        f = build_blurred_bg_filter(CENTER, 640, 360)
        assert "1080:1350" in f
        assert "crop=288:360" in f

    def test_3840x2160_dimensions(self):
        f = build_blurred_bg_filter(CENTER, 3840, 2160)
        assert "1080:1350" in f
        assert "crop=1728:2160" in f

    def test_empty_keypoints(self):
        f = build_blurred_bg_filter([], 1920, 1080)
        assert "1080:1350" in f
        assert "overlay" in f

    def test_single_keypoint(self):
        f = build_blurred_bg_filter([(5.0, 0.3, 0.5)], 1920, 1080)
        assert "crop=864:1080" in f

    def test_dynamic_pan_has_clip(self):
        kps = [(0.0, 0.2, 0.5), (5.0, 0.8, 0.5)]
        f = build_blurred_bg_filter(kps, 1920, 1080)
        assert "clip(" in f


# ---------------------------------------------------------------------------
# Vertical split filter
# ---------------------------------------------------------------------------


class TestVerticalSplitFilter:
    def test_1920x1080(self):
        f = build_vertical_split_filter(1920, 1080)
        assert "vstack=inputs=3" in f
        assert "1080x2" in f  # white divider
        assert "959" in f  # half panel height

    def test_1280x720(self):
        f = build_vertical_split_filter(1280, 720)
        assert "vstack" in f

    def test_640x360(self):
        f = build_vertical_split_filter(640, 360)
        assert "vstack" in f


# ---------------------------------------------------------------------------
# Pixel keypoint conversion
# ---------------------------------------------------------------------------


class TestPixelKeypoints:
    def test_center(self):
        result = _to_pixel_keypoints([(0.0, 0.5, 0.5)], 1920, 607, 1313)
        assert len(result) == 1
        _, px = result[0]
        assert 650 < px < 660  # ~656

    def test_left_edge_clamps_to_zero(self):
        result = _to_pixel_keypoints([(0.0, 0.0, 0.5)], 1920, 607, 1313)
        assert result[0][1] == 0

    def test_right_edge_clamps_to_max(self):
        result = _to_pixel_keypoints([(0.0, 1.0, 0.5)], 1920, 607, 1313)
        assert result[0][1] == 1313

    def test_multiple_keypoints(self):
        kps = [(0.0, 0.2, 0.5), (5.0, 0.5, 0.5), (10.0, 0.8, 0.5)]
        result = _to_pixel_keypoints(kps, 1920, 607, 1313)
        assert len(result) == 3
        assert result[0][1] < result[1][1] < result[2][1]
