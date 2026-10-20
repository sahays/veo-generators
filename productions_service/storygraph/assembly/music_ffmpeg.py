"""ffmpeg back-end for the assembly music bed (continuous score, ducked, scene crossfades)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import AssemblyCfg
from .music import MusicMixer, SceneSegment

logger = logging.getLogger(__name__)

_FFMPEG_TIMEOUT_S = 180
_MIN_VALID_MP4_BYTES = 256
_STDERR_TAIL_CHARS = 2000
_AFMT = "aformat=sample_rates=48000:channel_layouts=stereo"


def _log_ctx(what: str, why: str, **fields: object) -> dict[str, object]:
    return {
        "who": "storygraph.assembly",
        "where": "assembly.music_ffmpeg",
        "what": what,
        "why": why,
        "how": "ffmpeg acrossfade + sidechaincompress + amix",
        **fields,
    }


def _crossfade_s(segments: list[SceneSegment], cfg: AssemblyCfg) -> float:
    shortest = min(s.duration_s for s in segments)
    return max(0.0, min(cfg.music_crossfade_s, shortest / 2))


def _segment_sources(
    segments: list[SceneSegment], xf: float
) -> tuple[list[int], list[str]]:
    """Return (segment indices needing an ffmpeg input, per-segment filter chains)."""
    inputs: list[int] = []
    chains: list[str] = []
    last = len(segments) - 1
    for idx, seg in enumerate(segments):
        dur = seg.duration_s + (xf if idx < last else 0.0)
        if seg.audio:
            inputs.append(idx)
            src = f"[{len(inputs)}:a]atrim=duration={dur:.3f},asetpts=PTS-STARTPTS"
        else:
            src = f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.3f}"
        chains.append(f"{src},{_AFMT}[s{idx}]")
    return inputs, chains


def build_mix_filter(
    segments: list[SceneSegment], cfg: AssemblyCfg
) -> tuple[list[int], str]:
    """Build the filter graph; returns (segment indices that are ffmpeg inputs 1..N, graph)."""
    xf = _crossfade_s(segments, cfg) if len(segments) > 1 else 0.0
    inputs, chains = _segment_sources(segments, xf)
    label = "s0"
    for idx in range(1, len(segments)):
        nxt = f"x{idx}"
        chains.append(f"[{label}][s{idx}]acrossfade=d={xf:.3f}:c1=tri:c2=tri[{nxt}]")
        label = nxt
    chains += [
        f"[{label}]volume={cfg.music_gain:.3f}[score]",
        "[0:a]asplit=2[dia][key]",
        (
            f"[score][key]sidechaincompress=threshold={cfg.duck_threshold}"
            f":ratio={cfg.duck_ratio}:attack=20:release=400[ducked]"
        ),
        "[dia][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]",
    ]
    return inputs, ";".join(chains)


def _mix_command(
    tmp: Path, segments: list[SceneSegment], cfg: AssemblyCfg
) -> list[str]:
    inputs, graph = build_mix_filter(segments, cfg)
    cmd = ["ffmpeg", "-y", "-i", str(tmp / "video.mp4")]
    for seg_idx in inputs:
        music_path = tmp / f"music_{seg_idx:03d}.bin"
        music_path.write_bytes(segments[seg_idx].audio or b"")
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]
    return [
        *cmd,
        "-filter_complex",
        graph,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(tmp / "scored.mp4"),
    ]


def _run_mix(
    video: bytes, segments: list[SceneSegment], cfg: AssemblyCfg
) -> bytes | str:
    """Return mixed bytes, or an error string describing the ffmpeg failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "video.mp4").write_bytes(video)
        cmd = _mix_command(tmp, segments, cfg)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT_S, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{type(exc).__name__}: {exc}"
        out = tmp / "scored.mp4"
        if (
            proc.returncode == 0
            and out.is_file()
            and out.stat().st_size > _MIN_VALID_MP4_BYTES
        ):
            return out.read_bytes()
        return proc.stderr.decode("utf-8", errors="replace")[-_STDERR_TAIL_CHARS:] or (
            f"ffmpeg exited {proc.returncode} with empty output"
        )


def ffmpeg_music_mixer(
    video: bytes, segments: list[SceneSegment], cfg: AssemblyCfg
) -> bytes:
    """Mix the score under `video`; on any ffmpeg error log it and keep the unscored video."""
    if shutil.which("ffmpeg") is None:
        logger.error(
            "ffmpeg missing; final video left without music bed",
            extra=_log_ctx("music_mix_unavailable", "ffmpeg not on PATH"),
        )
        return video
    result = _run_mix(video, segments, cfg)
    if isinstance(result, bytes):
        return result
    logger.error(
        "ffmpeg music mix failed; final video left without music bed",
        extra=_log_ctx(
            "music_mix_failed",
            "ffmpeg returned an error",
            segment_count=len(segments),
            stderr_tail=result,
        ),
    )
    return video


def ffprobe_duration(clip: bytes) -> float | None:
    """Measured clip duration in seconds via ffprobe, or None when unavailable."""
    if shutil.which("ffprobe") is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp4") as fh:
        fh.write(clip)
        fh.flush()
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration"]
        try:
            proc = subprocess.run(
                [*cmd, "-of", "default=nw=1:nk=1", fh.name],
                capture_output=True,
                timeout=30,
                check=False,
            )
            return float(proc.stdout.decode().strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return None


def select_music_mixer(video_provider: str) -> MusicMixer | None:
    """ffmpeg mixer for real providers; mock clips (synthetic bytes) are never scored."""
    return None if video_provider == "mock" else ffmpeg_music_mixer
