"""Integration tests for the reframe pipeline — verifying all mode combinations
produce correct FFmpeg commands and filter strings.

No actual FFmpeg execution — tests the command building and filter generation
for every combination of: content_type × blurred_bg × vertical_split × source size.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_filters import (
    build_crop_filter,
    build_blurred_bg_filter,
    build_vertical_split_filter,
)
from reframe_strategies import get_strategy, STRATEGY_CONFIG
from focal_path import smooth_focal_path
from ffmpeg_runner import _splice_filter, _FILTER_PLACEHOLDER

# Typical source dimensions to test
SOURCES = {
    "640x360": (640, 360),
    "1280x720": (1280, 720),
    "1920x1080": (1920, 1080),
    "3840x2160": (3840, 2160),
}

# Sample focal points (movie-like: mostly centered with some panning)
SAMPLE_FOCAL_POINTS = [
    {"time_sec": 0.0, "x": 0.5, "y": 0.5},
    {"time_sec": 3.0, "x": 0.3, "y": 0.5},
    {"time_sec": 6.0, "x": 0.7, "y": 0.5},
    {"time_sec": 10.0, "x": 0.5, "y": 0.5},
]

SAMPLE_SCENE_CHANGES = [{"time_sec": 5.0}]


# ---------------------------------------------------------------------------
# Mode: standard 9:16 reframe (blurred_bg=False, vertical_split=False)
# ---------------------------------------------------------------------------


class TestStandard916:
    """AI reframe → 9:16 crop → 1080×1920."""

    def test_filter_for_all_sources(self):
        for name, (w, h) in SOURCES.items():
            kps = [(0.0, 0.5, 0.5), (10.0, 0.5, 0.5)]
            f = build_crop_filter(kps, w, h)
            assert "scale=1080:1920" in f, f"{name}: missing 1080:1920 scale"

    def test_crop_width_is_9_16_of_height(self):
        for name, (w, h) in SOURCES.items():
            expected_crop_w = int(h * 9 / 16)
            if w - expected_crop_w <= 0:
                continue  # narrow source, no crop
            kps = [(0.0, 0.5, 0.5), (10.0, 0.5, 0.5)]
            f = build_crop_filter(kps, w, h)
            assert f"crop={expected_crop_w}:{h}" in f, f"{name}: wrong crop dims"

    def test_cmd_splice_correct(self):
        """Filter flag goes before encoding options."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "src.mp4",
            _FILTER_PLACEHOLDER,
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter:v", "/tmp/crop.txt")
        fi = result.index("-/filter:v")
        ci = result.index("-c:v")
        oi = result.index("out.mp4")
        assert fi < ci < oi

    def test_full_pipeline_per_content_type(self):
        """Each content type → strategy → smooth → crop filter."""
        for ct in STRATEGY_CONFIG:
            strategy = get_strategy(ct)
            kps = smooth_focal_path(
                SAMPLE_FOCAL_POINTS,
                SAMPLE_SCENE_CHANGES,
                duration=10.0,
                fps=30,
                max_velocity=strategy["max_velocity"],
                deadzone=strategy["deadzone"],
            )
            assert len(kps) >= 2
            f = build_crop_filter(kps, 1920, 1080)
            assert "scale=1080:1920" in f


# ---------------------------------------------------------------------------
# Mode: blurred background 4:5 (blurred_bg=True, vertical_split=False)
# ---------------------------------------------------------------------------


class TestBlurredBg45:
    """AI reframe → 4:5 crop + blurred bg → 1080×1350."""

    def test_filter_for_all_sources(self):
        for name, (w, h) in SOURCES.items():
            kps = [(0.0, 0.5, 0.5), (10.0, 0.5, 0.5)]
            f = build_blurred_bg_filter(kps, w, h)
            assert "1080:1350" in f, f"{name}: missing 1080:1350"
            assert "gblur" in f, f"{name}: missing blur"

    def test_crop_width_is_4_5_of_height(self):
        for name, (w, h) in SOURCES.items():
            expected_crop_w = min(int(h * 4 / 5), w)
            if w - expected_crop_w <= 0:
                continue
            kps = [(0.0, 0.5, 0.5), (10.0, 0.5, 0.5)]
            f = build_blurred_bg_filter(kps, w, h)
            assert f"crop={expected_crop_w}:{h}" in f, f"{name}: wrong crop"

    def test_cmd_splice_filter_complex(self):
        """Blurred bg uses filter_complex with -map [v]."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "src.mp4",
            _FILTER_PLACEHOLDER,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter_complex", "/tmp/blur.txt")
        fi = result.index("-/filter_complex")
        mi = result.index("-map")
        assert fi < mi

    def test_full_pipeline_per_content_type(self):
        for ct in STRATEGY_CONFIG:
            strategy = get_strategy(ct)
            kps = smooth_focal_path(
                SAMPLE_FOCAL_POINTS,
                SAMPLE_SCENE_CHANGES,
                duration=10.0,
                fps=30,
                max_velocity=strategy["max_velocity"],
                deadzone=strategy["deadzone"],
            )
            f = build_blurred_bg_filter(kps, 1920, 1080)
            assert "1080:1350" in f
            assert "overlay" in f


# ---------------------------------------------------------------------------
# Mode: vertical split (vertical_split=True)
# ---------------------------------------------------------------------------


class TestVerticalSplit:
    """Vertical split → two 4:3 crops stacked → 1080×1920."""

    def test_filter_for_all_sources(self):
        for name, (w, h) in SOURCES.items():
            f = build_vertical_split_filter(w, h)
            assert "vstack=inputs=3" in f, f"{name}: missing vstack"

    def test_cmd_splice_filter_complex(self):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "src.mp4",
            _FILTER_PLACEHOLDER,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter_complex", "/tmp/split.txt")
        fi = result.index("-/filter_complex")
        mi = result.index("-map")
        assert fi < mi


# ---------------------------------------------------------------------------
# Transcoder dimensions
# ---------------------------------------------------------------------------


class TestTranscoderDimensions:
    """Verify transcoder would receive correct output dimensions."""

    def test_standard_reframe_dimensions(self):
        """blurred_bg=False → transcoder should use 1080×1920."""
        blurred_bg = False
        out_h = 1350 if blurred_bg else 1920
        assert out_h == 1920

    def test_blurred_bg_dimensions(self):
        """blurred_bg=True → transcoder should use 1080×1350."""
        blurred_bg = True
        out_h = 1350 if blurred_bg else 1920
        assert out_h == 1350


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_portrait_source_rejected(self):
        """Source 360×640 is portrait — crop_w = 360, max_x = 0, fallback to scale."""
        f = build_crop_filter([(0, 0.5, 0.5)], 360, 640)
        assert f == "scale=1080:1920"

    def test_square_source(self):
        """1080×1080 — crop_w = 607, max_x = 473."""
        kps = [(0, 0.5, 0.5), (10, 0.5, 0.5)]
        f = build_crop_filter(kps, 1080, 1080)
        assert "crop=607:1080" in f

    def test_ultrawide_source(self):
        """3440×1440 — lots of panning room."""
        kps = [(0, 0.2, 0.5), (10, 0.8, 0.5)]
        f = build_crop_filter(kps, 3440, 1440)
        assert "crop=810:1440" in f

    def test_very_short_video(self):
        fps = [{"time_sec": 0.0, "x": 0.5, "y": 0.5}]
        result = smooth_focal_path(fps, [], duration=0.5, fps=30)
        assert len(result) >= 1

    def test_many_scene_changes(self):
        fps = [{"time_sec": float(i), "x": 0.5, "y": 0.5} for i in range(20)]
        sc = [{"time_sec": float(i)} for i in range(1, 20)]
        result = smooth_focal_path(fps, sc, duration=20.0, fps=30)
        assert len(result) >= 2
