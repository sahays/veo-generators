"""Unit tests for reframe filter generation — aspect ratios and crop math."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_filters import (
    build_crop_filter,
    build_blurred_bg_filter,
    build_canvas_filter,
    build_split_filter,
    split_panel_geometry,
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
        assert "1080:1920" in f  # bg fills 9:16
        assert "1080:1350" in f  # fg is 4:5
        assert "crop=864:1080" in f
        assert "gblur=sigma=40" in f
        assert "overlay=0:285" in f  # centered vertically

    def test_1280x720_dimensions(self):
        f = build_blurred_bg_filter(CENTER, 1280, 720)
        assert "1080:1920" in f
        assert "1080:1350" in f
        assert "crop=576:720" in f

    def test_640x360_dimensions(self):
        f = build_blurred_bg_filter(CENTER, 640, 360)
        assert "1080:1920" in f
        assert "1080:1350" in f
        assert "crop=288:360" in f

    def test_3840x2160_dimensions(self):
        f = build_blurred_bg_filter(CENTER, 3840, 2160)
        assert "1080:1920" in f
        assert "1080:1350" in f
        assert "crop=1728:2160" in f

    def test_empty_keypoints(self):
        f = build_blurred_bg_filter([], 1920, 1080)
        assert "1080:1920" in f
        assert "overlay=0:285" in f

    def test_single_keypoint(self):
        f = build_blurred_bg_filter([(5.0, 0.3, 0.5)], 1920, 1080)
        assert "crop=864:1080" in f

    def test_dynamic_pan_has_clip(self):
        kps = [(0.0, 0.2, 0.5), (5.0, 0.8, 0.5)]
        f = build_blurred_bg_filter(kps, 1920, 1080)
        assert "clip(" in f


# ---------------------------------------------------------------------------
# Unified canvas filter (v2 adaptive letterboxing)
# ---------------------------------------------------------------------------


class TestCanvasFilter:
    SRC = (1920, 1080)

    def test_9x16_is_full_bleed_no_bars(self):
        f = build_canvas_filter(CENTER, *self.SRC, (9, 16))
        assert "[bg]" not in f  # foreground covers the canvas
        assert "overlay" not in f
        assert f.endswith("[v]")
        assert "scale=1080:1920" in f

    def test_4x5_letterboxed_over_blur(self):
        f = build_canvas_filter(CENTER, *self.SRC, (4, 5))
        assert "gblur" in f and "[bg]" in f
        assert "scale=1080:1350" in f
        assert "overlay=0:285" in f  # (1920-1350)//2
        assert f.endswith("[v]")

    def test_1x1_geometry(self):
        f = build_canvas_filter(CENTER, *self.SRC, (1, 1))
        assert "scale=1080:1080" in f
        assert "overlay=0:420" in f  # (1920-1080)//2
        assert "crop=1080:1080" in f

    def test_16x9_letterbox_full_width(self):
        f = build_canvas_filter(CENTER, *self.SRC, (16, 9))
        assert "scale=1080:608" in f
        assert "overlay=0:656" in f  # (1920-608)//2
        assert "crop=1920:1080" in f  # keeps the entire source width

    def test_even_dimensions(self):
        # All scale/crop targets must be even for libx264 + yuv420p.
        for ar in [(9, 16), (4, 5), (1, 1), (16, 9)]:
            f = build_canvas_filter(CENTER, *self.SRC, ar)
            import re

            for w, h in re.findall(r"scale=(\d+):(\d+)", f):
                assert int(w) % 2 == 0 and int(h) % 2 == 0, (ar, w, h)


class TestCanvas34:
    """3:4 output canvas (1080x1440). Full-bleed rung is (3,4); looser rungs bar."""

    SRC = (1920, 1080)
    OUT = (1080, 1440)

    def test_3x4_is_full_bleed_no_bars(self):
        f = build_canvas_filter(CENTER, *self.SRC, (3, 4), *self.OUT)
        assert "[bg]" not in f and "overlay" not in f  # fills the 3:4 canvas
        assert "scale=1080:1440" in f
        assert "crop=810:1080" in f  # 1080*3/4 wide, follows the subject
        assert f.endswith("[v]")

    def test_16x9_letterboxed_inside_3x4(self):
        f = build_canvas_filter(CENTER, *self.SRC, (16, 9), *self.OUT)
        assert "gblur" in f and "[bg]" in f
        assert "scale=1080:608" in f
        assert "overlay=0:416" in f  # (1440-608)//2
        assert "crop=1920:1080" in f  # entire source width kept

    def test_1x1_letterboxed_inside_3x4(self):
        f = build_canvas_filter(CENTER, *self.SRC, (1, 1), *self.OUT)
        assert "scale=1080:1080" in f
        assert "overlay=0:180" in f  # (1440-1080)//2

    def test_default_canvas_is_9x16(self):
        # Omitting out_w/out_h must reproduce the historical 9:16 output exactly.
        assert build_canvas_filter(CENTER, *self.SRC, (9, 16)) == build_canvas_filter(
            CENTER, *self.SRC, (9, 16), 1080, 1920
        )


# ---------------------------------------------------------------------------
# Vertical-split (stacked two-shot) filter
# ---------------------------------------------------------------------------


class TestSplitFilter:
    SRC = (1920, 1080)
    # Single static keypoint per panel → constant crop offset (near-static panels).
    LEFT = [(0.0, 0.3, 0.5)]
    RIGHT = [(0.0, 0.7, 0.5)]

    def test_panel_geometry_9x16(self):
        # Each panel is 1080x960 (half canvas); slice AR 9:8 → crop_w ~1214 (even).
        crop_w, panel_h, max_x = split_panel_geometry(*self.SRC)
        assert panel_h == 960
        assert crop_w == 1214  # even(1080 * 1080/960 = 1215)
        assert max_x == 1920 - 1214

    def test_builds_two_panels_vstacked(self):
        f = build_split_filter(self.LEFT, self.RIGHT, *self.SRC)
        assert f.count("crop=1214:1080") == 2  # one slice per subject
        assert f.count("scale=1080:960") == 2  # each fills a half-canvas panel
        assert "[top][bot]vstack[v]" in f
        assert "gblur" not in f  # panels fill the canvas — no blurred bars
        assert f.endswith("[v]")

    def test_panels_follow_their_own_subject(self):
        # Left subject pans toward 0.3, right toward 0.7 → different crop offsets.
        f = build_split_filter(self.LEFT, self.RIGHT, *self.SRC)
        top = f.split("[top];")[0]
        bot = f.split("[top];")[1].split("[bot];")[0]
        assert "crop=1214:1080:0:0" in top  # 0.3 center clamps left to 0
        assert "crop=1214:1080:706:0" in bot  # 0.7 center clamps to max_x

    def test_even_dimensions(self):
        import re

        f = build_split_filter(self.LEFT, self.RIGHT, *self.SRC)
        for w, h in re.findall(r"scale=(\d+):(\d+)", f):
            assert int(w) % 2 == 0 and int(h) % 2 == 0

    def test_3x4_canvas_panels(self):
        f = build_split_filter(CENTER, CENTER, *self.SRC, 1080, 1440)
        assert "scale=1080:720" in f  # half of 1440
        assert "[top][bot]vstack[v]" in f


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
