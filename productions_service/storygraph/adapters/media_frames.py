"""FFmpeg and Pillow representative frame extraction adapter for video clips."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat


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
    subprocess.run(
        cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=10, check=False
    )


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
        _ts_cur, png_cur = extracted[idx]
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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 critic probe: dense timestamped frames, scene cuts, audio energy, labels
# ─────────────────────────────────────────────────────────────────────────────

_PTS_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")
_SILENCE_DUR_RE = re.compile(r"silence_duration:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[0-9]+(?:\.[0-9]+)?)")
_LABEL_BAR_PX = 22


@dataclass(frozen=True)
class TimedFrame:
    """One sampled clip frame (downscaled PNG) and its timestamp in seconds."""

    t_s: float
    png: bytes


@dataclass(frozen=True)
class ClipProbe:
    """Deterministic measurements of a rendered clip used by the S9 critic."""

    frames: list[TimedFrame]
    last_frame_png: bytes
    duration_s: float = 0.0
    cut_times_s: tuple[float, ...] = ()
    voiced_ratio: float | None = None


def _run_capture(cmd: list[str], timeout_s: int = 30) -> str:
    """Run an ffmpeg/ffprobe argv (no shell) and return combined stdout+stderr text."""
    proc = subprocess.run(
        cmd,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout_s,
        check=False,
    )
    return proc.stdout.decode(errors="ignore") + proc.stderr.decode(errors="ignore")


def _probe_duration(in_mp4: Path) -> float:
    """Container duration in seconds via ffprobe (0.0 when unknown)."""
    out = _run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(in_mp4),
        ]
    )
    try:
        return max(0.0, float(out.strip().splitlines()[0]))
    except (ValueError, IndexError):
        return 0.0


def detect_scene_cuts(in_mp4: Path, threshold: float = 0.35) -> tuple[float, ...]:
    """Timestamps of hard cuts using ffmpeg's scene-change score (`select=gt(scene,T)`)."""
    out = _run_capture(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(in_mp4),
            "-an",
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ]
    )
    return tuple(round(float(m), 3) for m in _PTS_RE.findall(out))


def _has_audio_stream(in_mp4: Path) -> bool:
    out = _run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(in_mp4),
        ]
    )
    return bool(out.strip())


def audio_voiced_ratio(in_mp4: Path, duration_s: float) -> float | None:
    """Fraction of the clip above -35 dB (None when the clip has no audio stream)."""
    if duration_s <= 0.0 or not _has_audio_stream(in_mp4):
        return None
    out = _run_capture(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(in_mp4),
            "-vn",
            "-af",
            "silencedetect=n=-35dB:d=0.25",
            "-f",
            "null",
            "-",
        ]
    )
    silent = sum(float(v) for v in _SILENCE_DUR_RE.findall(out))
    starts = _SILENCE_START_RE.findall(out)
    if len(starts) > len(_SILENCE_DUR_RE.findall(out)):
        silent += max(0.0, duration_s - float(starts[-1]))
    return round(max(0.0, 1.0 - silent / duration_s), 3)


def _sample_dense(
    tmp: Path, in_mp4: Path, fps: float, max_frames: int, width: int
) -> list[TimedFrame]:
    """Uniform `fps` downscaled frames (frame k at t=k/fps), capped at `max_frames`."""
    _run_capture(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(in_mp4),
            "-vf",
            f"fps={fps},scale={width}:-2",
            "-frames:v",
            str(max_frames),
            str(tmp / "d_%03d.png"),
        ]
    )
    pngs = sorted(tmp.glob("d_*.png"))
    return [
        TimedFrame(t_s=round(k / fps, 3), png=p.read_bytes())
        for k, p in enumerate(pngs)
        if p.stat().st_size > 64
    ]


def _downscale_png(png: bytes, width: int) -> bytes:
    """Downscale a PNG to `width` px wide (aspect preserved) to bound VLM cost."""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    if img.width > width:
        img = img.resize((width, max(1, round(img.height * width / img.width))))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _probe_with_ffmpeg(
    clip_bytes: bytes, fps: float, max_frames: int, width: int
) -> ClipProbe | None:
    """Full ffmpeg probe; None if the bytes are not a decodable video."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        in_mp4 = tmp / "clip.mp4"
        in_mp4.write_bytes(clip_bytes)
        duration = _probe_duration(in_mp4)
        frames = _sample_dense(tmp, in_mp4, fps, max(2, max_frames - 1), width)
        _run_ffmpeg_frame(in_mp4, tmp / "last.png", ["-sseof", "-0.10"])
        if not frames:
            return None
        last_full = _read_valid_png(tmp / "last.png", frames[-1].png)
        last_t = max(duration - 0.10, frames[-1].t_s)
        frames.append(
            TimedFrame(t_s=round(last_t, 3), png=_downscale_png(last_full, width))
        )
        return ClipProbe(
            frames=frames,
            last_frame_png=last_full,
            duration_s=duration,
            cut_times_s=detect_scene_cuts(in_mp4),
            voiced_ratio=audio_voiced_ratio(in_mp4, duration),
        )


def probe_clip(
    clip_bytes: bytes, fps: float = 4.0, max_frames: int = 40, width: int = 384
) -> ClipProbe:
    """Dense timestamped frames (first..last, >=`fps`), scene cuts and audio energy."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe") and len(clip_bytes) > 256:
        try:
            probe = _probe_with_ffmpeg(clip_bytes, fps, max_frames, width)
        except (OSError, subprocess.SubprocessError):
            probe = None
        if probe is not None:
            return probe
    synthetic = _synthetic_fallback_frames(clip_bytes)
    frames = [TimedFrame(t_s=float(i), png=p) for i, p in enumerate(synthetic)]
    return ClipProbe(frames=frames, last_frame_png=synthetic[-1])


def label_image(png: bytes, label: str, width: int = 384) -> bytes:
    """Downscale `png` and add a top banner carrying `label` (image content untouched)."""
    try:
        img = Image.open(io.BytesIO(_downscale_png(png, width))).convert("RGB")
    except (OSError, ValueError):
        return png
    canvas = Image.new("RGB", (img.width, img.height + _LABEL_BAR_PX), (0, 0, 0))
    canvas.paste(img, (0, _LABEL_BAR_PX))
    ImageDraw.Draw(canvas).text((4, 5), label[:90], fill=(255, 255, 0))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()
