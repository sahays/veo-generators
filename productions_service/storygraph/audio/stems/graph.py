"""Stem-mix ffmpeg graph: dialogue + SFX (+ music ducked under dialogue only)."""

from __future__ import annotations

from dataclasses import dataclass

from ...schemas.stems import StemMix
from .loudness import loudness_gain_db

AFMT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
LIMIT = 0.95
DIALOGUE_MAX_BOOST_DB = 18.0
SFX_MAX_BOOST_DB = 6.0  # quiet beds stay quiet (no room-noise pumping)
MUSIC_MAX_BOOST_DB = 12.0


@dataclass(frozen=True)
class StemGains:
    """Static per-stem gains (dB) applied before summing."""

    dialogue_db: float
    sfx_db: float
    music_db: float


@dataclass(frozen=True)
class StemLevels:
    """Measured integrated loudness per stem (None = silent/unmeasurable)."""

    dialogue: float | None
    sfx: float | None
    music: float | None = None


def compute_gains(mix: StemMix, levels: StemLevels) -> StemGains:
    """Bring each stem to its LUFS target (bounded boost) plus the user trims."""
    return StemGains(
        dialogue_db=loudness_gain_db(
            levels.dialogue,
            mix.dialogue_lufs,
            DIALOGUE_MAX_BOOST_DB,
            mix.dialogue_gain_db,
        ),
        sfx_db=loudness_gain_db(
            levels.sfx, mix.sfx_lufs, SFX_MAX_BOOST_DB, mix.sfx_gain_db
        ),
        music_db=loudness_gain_db(
            levels.music, mix.music_lufs, MUSIC_MAX_BOOST_DB, mix.music_gain_db
        ),
    )


def stem_mix_graph(mix: StemMix, gains: StemGains, has_music: bool) -> str:
    """filter_complex producing `[aout]`; inputs 1=dialogue, 2=sfx, 3=music (optional)."""
    dia = f"[1:a]{AFMT},volume={gains.dialogue_db}dB"
    sfx = f"[2:a]{AFMT},volume={gains.sfx_db}dB[sfx]"
    if not has_music:
        mixdown = "[dia][sfx]amix=inputs=2:duration=first:normalize=0"
        return ";".join([f"{dia}[dia]", sfx, f"{mixdown},alimiter=limit={LIMIT}[aout]"])
    music = f"[3:a]{AFMT},volume={gains.music_db}dB[mus]"
    duck = (
        f"[mus][key]sidechaincompress=threshold={mix.duck_threshold}"
        f":ratio={mix.duck_ratio}:attack=20:release=400[ducked]"
    )
    mixdown = "[dia][sfx][ducked]amix=inputs=3:duration=first:normalize=0"
    return ";".join(
        [
            f"{dia},asplit=2[dia][key]",
            sfx,
            music,
            duck,
            f"{mixdown},alimiter=limit={LIMIT}[aout]",
        ]
    )
