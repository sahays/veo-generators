"""S10 stem rendering (`audio.mode=stems`): Omni picture + stored stems per shot.

Each ready shot's run stems (`GenerationRun.stems`) are rendered over its picture with a
`StemMix` built from config; Omni's guide audio is discarded. The dialogue stems are also
concatenated into one key track so the S5 music bed ducks under dialogue only (not SFX).
A shot without stems keeps its Omni clip and disables the dialogue key (logged).
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..audio.stems import RenderTools, StemAudio, render_stem_clip
from ..config import AssemblyCfg, AudioCfg
from ..repo import Repo
from ..schema import GenerationRun, StemMix, StemSet
from .readiness import ReadyShot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StemClips:
    clips: list[bytes]
    duck_key: bytes | None  # stitched dialogue stem (None when any shot lacks stems)


def stem_mix_for(stems: StemSet, audio: AudioCfg, assembly: AssemblyCfg) -> StemMix:
    """Config -> typed per-clip mix contract (music is mixed project-wide in S10)."""
    return StemMix(
        dialogue_uri=stems.dialogue_uri,
        sfx_uri=stems.sfx_uri,
        dialogue_lufs=audio.dialogue_lufs,
        sfx_lufs=audio.sfx_lufs,
        music_lufs=audio.music_lufs,
        duck_threshold=assembly.duck_threshold,
        duck_ratio=assembly.duck_ratio,
    )


def concat_args(parts: list[Path], out: Path) -> list[str]:
    inputs = [arg for p in parts for arg in ("-i", str(p))]
    labels = "".join(f"[{i}:a]" for i in range(len(parts)))
    graph = f"{labels}concat=n={len(parts)}:v=0:a=1[k]"
    return [*inputs, "-filter_complex", graph, "-map", "[k]", "-ar", "48000", str(out)]


def _duck_key(dialogue: list[bytes], tools: RenderTools) -> bytes:
    with tempfile.TemporaryDirectory(prefix="duck_key_") as tmp:
        parts = [Path(tmp) / f"d{i}.flac" for i in range(len(dialogue))]
        for path, data in zip(parts, dialogue, strict=True):
            path.write_bytes(data)
        out = Path(tmp) / "key.wav"
        tools.media.run(concat_args(parts, out))
        return out.read_bytes()


def _log_missing(missing: list[str]) -> None:
    logger.warning(
        "Shots without stems keep their Omni clip audio",
        extra={
            "who": "storygraph.assembly",
            "where": "assembly.stem_clips",
            "what": "stems_missing",
            "when": datetime.now(UTC).isoformat(),
            "why": "stems stage failed or has not run for these shots",
            "how": "picture kept as rendered; dialogue duck key disabled",
            "shot_ids": missing,
        },
    )


def render_stem_clips(
    repo: Repo,
    ready: list[ReadyShot],
    pictures: list[bytes],
    cfg: tuple[AudioCfg, AssemblyCfg],
    tools: RenderTools,
) -> StemClips:
    """Render each shot from its stems; collect dialogue stems for the music duck key."""
    runs: dict[str, GenerationRun] = {r.id: r for r in repo.list_generation_runs()}
    clips: list[bytes] = []
    dialogue: list[bytes] = []
    missing: list[str] = []
    for shot, picture in zip(ready, pictures, strict=True):
        stems = runs[shot.run_id].stems if shot.run_id in runs else None
        if stems is None:
            clips.append(picture)
            missing.append(shot.shot_id)
            continue
        audio = StemAudio(
            repo.blobs.get_bytes(stems.dialogue_uri),
            repo.blobs.get_bytes(stems.sfx_uri),
        )
        mix = stem_mix_for(stems, *cfg)
        clips.append(
            render_stem_clip(picture, audio, mix, tools, shot_ref=shot.shot_id)
        )
        dialogue.append(audio.dialogue)
    if missing:
        _log_missing(missing)
    key = _duck_key(dialogue, tools) if dialogue and not missing else None
    return StemClips(clips, key)
