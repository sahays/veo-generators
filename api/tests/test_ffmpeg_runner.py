"""Unit tests for FFmpeg command splicing and filter placement."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffmpeg_runner import _splice_filter, _FILTER_PLACEHOLDER


class TestSpliceFilterPlaceholder:
    """When cmd contains the placeholder, replace it with flag+path."""

    def test_basic_replacement(self):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "in.mp4",
            _FILTER_PLACEHOLDER,
            "-c:v",
            "libx264",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter:v", "/tmp/f.txt")
        assert _FILTER_PLACEHOLDER not in result
        assert "-/filter:v" in result
        assert "/tmp/f.txt" in result

    def test_filter_before_encoding(self):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "in.mp4",
            _FILTER_PLACEHOLDER,
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter:v", "/tmp/f.txt")
        fi = result.index("-/filter:v")
        ci = result.index("-c:v")
        assert fi < ci

    def test_filter_complex_with_map(self):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "in.mp4",
            _FILTER_PLACEHOLDER,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter_complex", "/tmp/f.txt")
        fi = result.index("-/filter_complex")
        mi = result.index("-map")
        assert fi < mi

    def test_blurred_bg_reframe_cmd(self):
        """Simulates actual _build_reframe_cmd output for blurred_bg."""
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
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter_complex", "/tmp/blur.txt")
        # filter_complex must come before -map
        fi = result.index("-/filter_complex")
        mi = result.index("-map")
        oi = result.index("out.mp4")
        assert fi < mi < oi

    def test_standard_reframe_cmd(self):
        """Simulates actual _build_reframe_cmd output for standard 9:16."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "src.mp4",
            _FILTER_PLACEHOLDER,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
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

    def test_with_seek_and_duration(self):
        """Cmd with -ss and -t (chunked reframe)."""
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            "60.000",
            "-i",
            "src.mp4",
            "-t",
            "120.000",
            _FILTER_PLACEHOLDER,
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter:v", "/tmp/f.txt")
        fi = result.index("-/filter:v")
        si = result.index("-ss")
        ii = result.index("-i")
        assert si < ii < fi


class TestSpliceFilterAutoInsert:
    """When no placeholder, inserts after the last -i arg."""

    def test_single_input(self):
        cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "libx264", "out.mp4"]
        result = _splice_filter(cmd, "-vf", "/tmp/f.txt")
        fi = result.index("-vf")
        assert result[fi - 2] == "-i"  # -i is 2 positions before

    def test_two_inputs(self):
        """Overlay: two -i inputs, filter goes after the second."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            "a.mp4",
            "-i",
            "b.mp4",
            "-c:v",
            "libx264",
            "out.mp4",
        ]
        result = _splice_filter(cmd, "-/filter_complex", "/tmp/f.txt")
        fi = result.index("-/filter_complex")
        # Should be right after "b.mp4"
        assert result[fi - 1] == "b.mp4"
