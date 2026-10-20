"""FFmpeg and Pillow representative frame extraction adapter for video clips."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


def _run_ffmpeg_frame(in_mp4: Path, out_png: Path, seek_args: list[str]) -> None:
    """Extract a single frame from `in_mp4` to `out_png` using `seek_args`."""
    cmd = [
        "ffmpeg",
        "-y",
        *seek_args,
        "-i",
        str(in_mp4),
        "-frames:v",
        "1",
        str(out_png),
    ]
    subprocess.run(cmd, capture_output=True, timeout=10, check=False)


def _read_valid_png(png_path: Path, fallback: bytes) -> bytes:
    """Read `png_path` bytes if non-empty, otherwise return `fallback`."""
    if png_path.is_file() and png_path.stat().st_size > 64:
        return png_path.read_bytes()
    return fallback


_FFMPEG_SEEKS: tuple[tuple[str, list[str]], ...] = (
    ("f0.png", []),
    ("f1.png", ["-ss", "1.0"]),
    ("f2.png", ["-ss", "2.0"]),
    ("f3.png", ["-ss", "3.0"]),
    ("f4.png", ["-ss", "4.0"]),
    ("last.png", ["-sseof", "-0.15"]),
)


def _try_ffmpeg_frames(clip_bytes: bytes) -> list[bytes] | None:
    """Attempt extracting dense timeline PNG frames (0s, 1s, 2s, 3s, 4s, last) via ffmpeg."""
    if not shutil.which("ffmpeg") or len(clip_bytes) <= 256:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            in_mp4 = tmp_path / "clip.mp4"
            in_mp4.write_bytes(clip_bytes)
            for fname, seek_args in _FFMPEG_SEEKS:
                _run_ffmpeg_frame(in_mp4, tmp_path / fname, seek_args)
            first_png = tmp_path / "f0.png"
            if first_png.is_file() and first_png.stat().st_size > 64:
                out: list[bytes] = []
                prev = first_png.read_bytes()
                for fname, _ in _FFMPEG_SEEKS:
                    prev = _read_valid_png(tmp_path / fname, prev)
                    out.append(prev)
                return out
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _synthetic_fallback_frames(clip_bytes: bytes) -> list[bytes]:
    """Generate 3 deterministic RGB PNG frames hashed from `clip_bytes`."""
    frames: list[bytes] = []
    digest = hashlib.sha256(clip_bytes).digest()
    for i in range(3):
        color = (
            (digest[i * 3] % 180) + 30,
            (digest[i * 3 + 1] % 180) + 30,
            (digest[i * 3 + 2] % 180) + 30,
        )
        img = Image.new("RGB", (320, 180), color=color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        frames.append(buf.getvalue())
    return frames


def extract_representative_frames_png(clip_bytes: bytes) -> list[bytes]:
    """Extract representative PNG frames from rendered MP4 clip bytes."""
    ffmpeg_frames = _try_ffmpeg_frames(clip_bytes)
    if ffmpeg_frames is not None:
        return ffmpeg_frames
    return _synthetic_fallback_frames(clip_bytes)


def _mean_l1_diff(png_a: bytes, png_b: bytes) -> float | None:
    """Compute mean L1 RGB pixel difference in [0.0, 255.0] between two PNG images."""
    try:
        img_a = Image.open(io.BytesIO(png_a)).convert("RGB").resize((64, 36))
        img_b = Image.open(io.BytesIO(png_b)).convert("RGB").resize((64, 36))
        diff = ImageChops.difference(img_a, img_b)
        stat = ImageStat.Stat(diff)
        return sum(stat.mean) / max(1, len(stat.mean))
    except Exception:  # noqa: BLE001
        return None


def detect_frame_anomalies(
    frames: list[bytes],
    prev_last_frame: bytes | None = None,
    ref_frames: list[bytes] | None = None,
) -> list[str]:
    """Deterministically detect frozen clips, start-frame bleed, or extreme cut jumps using pixel L1 distance."""
    flags: list[str] = []
    if len(frames) >= 2:
        diffs = [
            d
            for i in range(len(frames) - 1)
            if (d := _mean_l1_diff(frames[i], frames[i + 1])) is not None
        ]
        if diffs and max(diffs) < 0.25:
            flags.append("frozen_frame")
        if len(diffs) >= 2 and diffs[0] > 42.0 and max(diffs[1:]) < 24.0:
            flags.append("start_frame_bleed")
    if ref_frames and frames:
        for ref_png in ref_frames:
            ref_diff = _mean_l1_diff(frames[0], ref_png)
            if ref_diff is not None and ref_diff < 22.0:
                flags.append("start_frame_bleed")
                break
    if prev_last_frame and frames:
        seam_diff = _mean_l1_diff(prev_last_frame, frames[0])
        if seam_diff is not None and seam_diff > 180.0:
            flags.append("cut_discontinuity")
    return list(dict.fromkeys(flags))


_EARLY_TRIM_SEEKS: tuple[tuple[float, str], ...] = (
    (0.0, "e0.png"),
    (0.2, "e1.png"),
    (0.4, "e2.png"),
    (0.6, "e3.png"),
    (0.8, "e4.png"),
    (1.0, "e5.png"),
)


def _detect_head_trim_seconds(
    tmp_path: Path, in_mp4: Path, ref_frames: list[bytes]
) -> float:
    """Compute how many leading seconds (0.35s-0.85s) to trim to remove start-frame/ref-sheet hold or flash."""
    extracted: list[tuple[float, bytes]] = []
    for ts, fname in _EARLY_TRIM_SEEKS:
        out_png = tmp_path / fname
        seek = ["-ss", f"{ts:.2f}"] if ts > 0 else []
        _run_ffmpeg_frame(in_mp4, out_png, seek)
        if out_png.is_file() and out_png.stat().st_size > 64:
            extracted.append((ts, out_png.read_bytes()))
    if len(extracted) < 3:
        return 0.0
    trim_ts = 0.40
    for idx in range(len(extracted) - 1):
        ts_cur, png_cur = extracted[idx]
        ts_nxt, png_nxt = extracted[idx + 1]
        step_diff = _mean_l1_diff(png_cur, png_nxt)
        if step_diff is not None and step_diff > 28.0 and ts_nxt <= 0.85:
            trim_ts = max(trim_ts, ts_nxt + 0.05)
        for ref_png in ref_frames:
            ref_d = _mean_l1_diff(png_cur, ref_png)
            if ref_d is not None and ref_d < 28.0 and ts_nxt <= 0.85:
                trim_ts = max(trim_ts, ts_nxt + 0.05)
    return min(trim_ts, 0.85)


def trim_leading_reference_or_static_frames(
    clip_bytes: bytes,
    ref_frames: list[bytes] | None = None,
    has_conditioning_image: bool = True,
) -> bytes:
    """Strip leading conditioned start-frame hold or reference-sheet flash from a rendered MP4 clip."""
    if (
        not has_conditioning_image
        or not shutil.which("ffmpeg")
        or len(clip_bytes) <= 1024
    ):
        return clip_bytes
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            in_mp4 = tmp_path / "in.mp4"
            out_mp4 = tmp_path / "out.mp4"
            in_mp4.write_bytes(clip_bytes)
            trim_s = _detect_head_trim_seconds(tmp_path, in_mp4, ref_frames or [])
            if trim_s <= 0.05:
                return clip_bytes
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{trim_s:.2f}",
                "-i",
                str(in_mp4),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(out_mp4),
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
            if (
                proc.returncode == 0
                and out_mp4.is_file()
                and out_mp4.stat().st_size > 512
            ):
                return out_mp4.read_bytes()
    except (OSError, subprocess.SubprocessError):
        return clip_bytes
    return clip_bytes
