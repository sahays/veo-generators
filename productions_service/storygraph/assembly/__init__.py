"""Final assembly package: shot readiness gate, clip stitching, and `assemble()`."""

from .assembler import (
    PARTIAL_NOTE_PREFIX,
    STATUS_COMPLETED,
    STATUS_COMPLETED_PARTIAL,
    assemble,
)
from .loudness import (
    EBU_R128,
    LoudnessTarget,
    MasterNormalizer,
    ffmpeg_loudnorm,
    select_normalizer,
)
from .music import MusicMixer, SceneSegment, apply_music_bed, build_scene_segments
from .music_ffmpeg import ffmpeg_music_mixer, select_music_mixer
from .readiness import (
    AssemblyReadiness,
    BlockingShot,
    ReadyShot,
    evaluate_shot_readiness,
    story_ordered_shots,
)
from .stitch import ClipStitcher, ffmpeg_stitch, mock_concat_stitch, select_stitcher
from .timing import ClipTiming, DurationProbe, measure_clip_timings

__all__ = [
    "EBU_R128",
    "PARTIAL_NOTE_PREFIX",
    "STATUS_COMPLETED",
    "STATUS_COMPLETED_PARTIAL",
    "AssemblyReadiness",
    "BlockingShot",
    "ClipStitcher",
    "ClipTiming",
    "DurationProbe",
    "LoudnessTarget",
    "MasterNormalizer",
    "MusicMixer",
    "ReadyShot",
    "SceneSegment",
    "apply_music_bed",
    "assemble",
    "build_scene_segments",
    "evaluate_shot_readiness",
    "ffmpeg_loudnorm",
    "ffmpeg_music_mixer",
    "ffmpeg_stitch",
    "measure_clip_timings",
    "mock_concat_stitch",
    "select_music_mixer",
    "select_normalizer",
    "select_stitcher",
    "story_ordered_shots",
]
