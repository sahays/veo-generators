"""Fixed character voices + per-clip voiceover sync.

registry   one deterministic Gemini TTS voice per speaking character (stored on Entity)
timing     scripted lines aligned to the clip transcript
timefit    bounded atempo fitting that never cuts words
separation Omni speech removal (ducking or Demucs)
mix/media  ffmpeg graph + muxing
sync       `voice_clip` orchestrator
"""

from .registry import assign_cast_voices, ensure_cast_voices, pick_voice_name, set_voice
from .sync import LineSynthesizer, SyncDeps, VoicedClip, voice_clip
from .timing import SpeechLine

__all__ = [
    "LineSynthesizer",
    "SpeechLine",
    "SyncDeps",
    "VoicedClip",
    "assign_cast_voices",
    "ensure_cast_voices",
    "pick_voice_name",
    "set_voice",
    "voice_clip",
]
