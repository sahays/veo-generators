"""Keyframe animation media: animatic timing/encoding, interp segments, stitching."""

from __future__ import annotations

import itertools
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from storygraph.keyframes.animate.media import build_animatic, stitch
from storygraph.keyframes.animate.timing import (
    animatic_schedule,
    concat_manifest,
    segment_bounds,
)

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg missing"
)


def _duration(mp4: bytes) -> float:
    with tempfile.NamedTemporaryFile(suffix=".mp4") as fh:
        fh.write(mp4)
        fh.flush()
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                fh.name,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    return float(out.stdout.strip())


def _png(color: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "f.png"
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=64x36",
                "-frames:v",
                "1",
                str(out),
            ],
            check=True,
        )
        return out.read_bytes()


def test_animatic_schedule_centres_keyframes_and_sums_to_clip() -> None:
    sched = animatic_schedule(10, 9.0)
    assert sched[0] == sched[-1] == 0.5 and set(sched[1:-1]) == {1.0}
    assert sum(sched) == pytest.approx(9.0)
    # Keyframe t is on screen at second t: its slot spans [t - 0.5, t + 0.5].
    starts = [sum(sched[:i]) for i in range(10)]
    assert all(
        s <= t < s + d or t == 9
        for t, (s, d) in enumerate(zip(starts, sched, strict=True))
    )


def test_concat_manifest_repeats_last_file_for_its_duration() -> None:
    text = concat_manifest(["/a.png", "/b.png"], [0.5, 0.5]).splitlines()
    assert text == [
        "file '/a.png'",
        "duration 0.500",
        "file '/b.png'",
        "duration 0.500",
        "file '/b.png'",
    ]


@pytest.mark.parametrize(
    ("last_t", "stride", "want"),
    [
        (9, 3, [(0, 3), (3, 6), (6, 9)]),
        (9, 5, [(0, 5), (5, 9)]),
        (9, 4, [(0, 4), (4, 9)]),  # 1s tail is below Omni's 3s minimum -> merged
        (9, 2, [(0, 3), (3, 6), (6, 9)]),  # stride clamped to Omni's minimum
        (8, 10, [(0, 8)]),
    ],
)
def test_segment_bounds_cover_clip_within_omni_limits(
    last_t: int, stride: int, want: list[tuple[int, int]]
) -> None:
    got = segment_bounds(last_t, stride)
    assert got == want
    assert got[0][0] == 0 and got[-1][1] == last_t
    assert all(a == b for (_, a), (b, _) in itertools.pairwise(got))


@needs_ffmpeg
def test_build_animatic_lasts_exactly_the_clip() -> None:
    frames = [_png(c) for c in ("red", "green", "blue", "white", "black")]
    mp4 = build_animatic(frames, 4.0)
    assert _duration(mp4) == pytest.approx(4.0, abs=0.1)


def _rgb_at(mp4: bytes, t: float) -> tuple[int, int, int]:
    with tempfile.NamedTemporaryFile(suffix=".mp4") as fh:
        fh.write(mp4)
        fh.flush()
        raw = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-ss",
                f"{t:.2f}",
                "-i",
                fh.name,
                "-frames:v",
                "1",
                "-vf",
                "scale=1:1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
            check=True,
        ).stdout
    return raw[0], raw[1], raw[2]


@needs_ffmpeg
def test_animatic_shows_each_keyframe_at_its_second() -> None:
    mp4 = build_animatic([_png("red"), _png("lime"), _png("blue")], 2.0)
    dominant = [max(range(3), key=_rgb_at(mp4, t).__getitem__) for t in (0.1, 1.0, 1.9)]
    assert dominant == [
        0,
        1,
        2,
    ]  # red at 0s, green at 1s, final blue keyframe at the end


@needs_ffmpeg
def test_stitch_trims_segments_to_planned_durations() -> None:
    seg = build_animatic([_png("red"), _png("blue")], 3.0)
    out = stitch([seg, seg, seg], [3.0, 3.0, 2.0])  # last segment trimmed (Omni min 3s)
    assert _duration(out) == pytest.approx(8.0, abs=0.15)
