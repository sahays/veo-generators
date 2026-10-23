"""Render a clip from Omni's picture + our stems (`StemMix`) — runs in assembly (S10)."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ...schemas.stems import StemMix
from ..voice.logs import log_ctx
from ..voice.media import MediaTools
from .graph import StemGains, StemLevels, compute_gains, stem_mix_graph
from .loudness import measure_lufs

logger = logging.getLogger(__name__)
Measure = Callable[[Path], float | None]


@dataclass(frozen=True)
class StemAudio:
    """Stem bytes resolved from `StemMix` URIs."""

    dialogue: bytes
    sfx: bytes
    music: bytes | None = None


@dataclass(frozen=True)
class RenderTools:
    media: MediaTools = field(default_factory=MediaTools)
    measure: Measure = measure_lufs


def render_args(
    paths: list[Path], graph: str, out: Path, clip_s: float, has_music: bool
) -> list[str]:
    """ffmpeg args: picture (0) + dialogue (1) + sfx (2) [+ looped music (3)]."""
    args = ["-i", str(paths[0]), "-i", str(paths[1]), "-i", str(paths[2])]
    if has_music:
        args += ["-stream_loop", "-1", "-i", str(paths[3])]
    return [
        *args, "-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{clip_s:.3f}",
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def _write(work: Path, picture: bytes, audio: StemAudio) -> list[Path]:
    blobs = [("picture.mp4", picture), ("dialogue.flac", audio.dialogue)]
    blobs += [("sfx.flac", audio.sfx)]
    if audio.music is not None:
        blobs.append(("music.bin", audio.music))
    paths = [work / name for name, _ in blobs]
    for path, (_, data) in zip(paths, blobs, strict=True):
        path.write_bytes(data)
    return paths


def render_stem_clip(
    picture: bytes,
    audio: StemAudio,
    mix: StemMix,
    tools: RenderTools,
    shot_ref: str = "",
) -> bytes:
    """Omni picture (video stream copied) + mixed stems; Omni's own audio is discarded."""
    with tempfile.TemporaryDirectory(prefix="stem_mix_") as tmp:
        work = Path(tmp)
        paths = _write(work, picture, audio)
        has_music = audio.music is not None
        levels = StemLevels(
            tools.measure(paths[1]),
            tools.measure(paths[2]),
            tools.measure(paths[3]) if has_music else None,
        )
        gains: StemGains = compute_gains(mix, levels)
        out = work / "mixed.mp4"
        graph = stem_mix_graph(mix, gains, has_music)
        clip_s = tools.media.probe(paths[0])
        tools.media.run(render_args(paths, graph, out, clip_s, has_music))
        logger.info(
            "Clip rendered from stems",
            extra=log_ctx(
                "audio.stems.render",
                "stem_clip_rendered",
                "S10 mixes our stems over Omni's picture (guide audio discarded)",
                "measured LUFS -> bounded gains -> amix (+ music sidechain on dialogue)",
                shot_ref=shot_ref,
                gains_db=[gains.dialogue_db, gains.sfx_db, gains.music_db],
            ),
        )
        return out.read_bytes()
