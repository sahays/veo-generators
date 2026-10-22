"""Gemini TTS (Vertex) line synthesizer: fixed prebuilt voice, language-aware, cached."""

from __future__ import annotations

import logging
import os
import time

from ..audio.voice.media import pcm_to_wav
from ..errors import StoryGraphError
from ..omni.voice import language_code
from ..schemas.voice import VoiceProfile
from .bounded_cache import BoundedCache, digest

logger = logging.getLogger(__name__)
PCM_RATE = 24_000
MAX_ATTEMPTS = 3
_LANG_NAMES = {
    "hi": "Hindi",
    "en": "English",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "mr": "Marathi",
}


MAX_S_PER_WORD = (
    0.75  # ~2x a slow speaking rate; longer audio means instructions were read
)
BASE_SLACK_S = 1.5
MIN_TARGET_S = 0.5


def pace_clause(target_s: float | None) -> str:
    """Pace instruction fitting the line into Omni's speech window (no colons)."""
    if target_s is None or target_s < MIN_TARGET_S:
        return ""
    return f", at a brisk natural pace so the whole line takes about {target_s:.1f} seconds,"


def tts_prompt(
    text: str, voice: VoiceProfile, lang: str, target_s: float | None
) -> str:
    """Single "Say ...: text" directive (no other colons) so only `text` is spoken.

    Per-line delivery hints are intentionally not sent: they shifted pitch between lines
    (voiceover_sync_v1) and slowed delivery past the lip window.
    """
    lang_name = _LANG_NAMES.get(language_code(lang).split("-")[0].lower(), "")
    in_lang = f" in {lang_name}" if lang_name else ""
    style = voice.style_prompt.replace(":", ",") or "natural"
    return f"Say{in_lang}{pace_clause(target_s)} in a {style} voice: {text}"


def plausible_length(pcm: bytes, text: str) -> bool:
    """False when the audio is far longer than the line (TTS read the instructions)."""
    seconds = len(pcm) / (2 * PCM_RATE)
    return seconds <= BASE_SLACK_S + MAX_S_PER_WORD * max(1, len(text.split()))


class GeminiTTSSynthesizer:
    """`LineSynthesizer` backed by Gemini TTS `generate_content` (AUDIO modality)."""

    def __init__(self, project: str | None = None, location: str | None = None) -> None:
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GEMINI_TTS_REGION", "global")
        self._cache: BoundedCache[bytes] = BoundedCache(256)

    def synthesize(
        self, text: str, voice: VoiceProfile, lang: str, target_s: float | None
    ) -> bytes:
        target = round(target_s, 1) if target_s is not None else None
        key = digest(
            text.encode(),
            f"{voice.model}|{voice.voice_name}|{voice.style_prompt}|{lang}|{target}",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        pcm = self._call_with_retry(tts_prompt(text, voice, lang, target), voice, lang)
        if not plausible_length(pcm, text):
            pcm = self._call_with_retry(
                text, voice, lang
            )  # plain text: nothing else to read
        wav = pcm_to_wav(pcm, PCM_RATE)
        self._cache.put(key, wav)
        return wav

    def _call_with_retry(self, prompt: str, voice: VoiceProfile, lang: str) -> bytes:
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._call(prompt, voice, lang)
            except Exception as exc:  # noqa: BLE001 - transient quota/5xx; retried
                last = exc
                logger.warning(
                    "Gemini TTS call failed; retrying",
                    extra={
                        "who": "storygraph.adapters.gemini_tts",
                        "where": "GeminiTTSSynthesizer._call",
                        "what": "tts_retry",
                        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "why": str(exc)[:200],
                        "how": f"attempt {attempt}/{MAX_ATTEMPTS}",
                        "voice_name": voice.voice_name,
                    },
                )
                time.sleep(2**attempt)
        raise StoryGraphError(f"Gemini TTS ({voice.model}) failed: {last}") from last

    def _call(self, prompt: str, voice: VoiceProfile, lang: str) -> bytes:
        from google import genai
        from google.genai import types

        client = genai.Client(
            vertexai=True, project=self.project, location=self.location
        )
        speech = types.SpeechConfig(
            language_code=language_code(lang),
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice.voice_name
                )
            ),
        )
        resp = client.models.generate_content(
            model=voice.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"], speech_config=speech
            ),
        )
        part = resp.candidates[0].content.parts[0] if resp.candidates else None
        data = part.inline_data.data if part and part.inline_data else None
        if not data:
            raise StoryGraphError("Gemini TTS returned no audio")
        return data
