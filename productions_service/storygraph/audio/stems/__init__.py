"""Stem-based clip audio (`audio.mode=stems`): Omni audio guides timing, our stems are mixed.

build   guide track -> dialogue stem (fixed-voice TTS) + SFX stem
sfx     SFX stem sources (demucs no_vocals with residual-voice duck)
graph   stem gains (LUFS targets) + ffmpeg mix graph (music ducked under dialogue)
render  assembly-time render of picture + `StemMix`
"""

from .build import BuiltStems, StemDeps, build_stems
from .render import RenderTools, StemAudio, render_stem_clip
from .sfx import DemucsSfx, SfxStemSource

__all__ = [
    "BuiltStems",
    "DemucsSfx",
    "RenderTools",
    "SfxStemSource",
    "StemAudio",
    "StemDeps",
    "build_stems",
    "render_stem_clip",
]
