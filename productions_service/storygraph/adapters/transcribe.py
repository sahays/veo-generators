"""Clip audio transcription adapter (Gemini audio understanding), cached by content digest."""

from __future__ import annotations

import os
from typing import Protocol

from pydantic import BaseModel, Field

from ..errors import StoryGraphError
from .bounded_cache import BoundedCache, digest
from .governor import governed


class TranscriptSegment(BaseModel):
    t_start: float = Field(description="Segment start in seconds.")
    t_end: float = Field(description="Segment end in seconds.")
    text: str = Field(
        description="Verbatim words in the original script (no translation)."
    )
    speaker: str = Field(
        default="", description="Visible speaking subject name, if known."
    )
    lang: str = Field(default="", description="BCP-47 language code, e.g. 'en', 'hi'.")


class Transcript(BaseModel):
    """Ordered speech segments; `available=False` means no transcription was possible."""

    segments: list[TranscriptSegment] = Field(default_factory=list)
    available: bool = True


class TranscriptPayload(BaseModel):
    """Model-facing response schema: `segments` is required; availability is decided by us."""

    segments: list[TranscriptSegment] = Field(
        description="Every utterance in order; empty list only if nobody speaks."
    )


FALLBACK_TRANSCRIBE_MODEL = "gemini-3.1-pro-preview"


class Transcriber(Protocol):
    def transcribe(
        self, clip_bytes: bytes, speakers: list[str], lang_hints: list[str]
    ) -> Transcript: ...


def _transcribe_prompt(speakers: list[str], lang_hints: list[str]) -> str:
    return (
        "Transcribe every spoken word in this clip verbatim, in its original script "
        "(Devanagari for Hindi; never translate or transliterate). One segment per "
        "utterance with start/end seconds. Attribute each segment to the on-screen subject "
        f"whose mouth moves (candidates: {', '.join(speakers) or 'unknown'}). Expected "
        f"languages: {', '.join(lang_hints) or 'any'}. Non-speech sounds are not segments."
    )


class GeminiTranscriber:
    """Cheap separate transcription call; results cached per clip digest."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash",
        project: str | None = None,
        fallback_model: str | None = FALLBACK_TRANSCRIBE_MODEL,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("GEMINI_REGION", "global")
        self._cache: BoundedCache[Transcript] = BoundedCache(128)

    def transcribe(
        self, clip_bytes: bytes, speakers: list[str], lang_hints: list[str]
    ) -> Transcript:
        key = digest(clip_bytes, f"{self.model}|{speakers}|{lang_hints}")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        prompt = _transcribe_prompt(speakers, lang_hints)
        result = self._call(clip_bytes, prompt, self.model)
        if not result.segments and self.fallback_model:
            result = self._call(clip_bytes, prompt, self.fallback_model)
        self._cache.put(key, result)
        return result

    def _call(self, clip_bytes: bytes, prompt: str, model: str) -> Transcript:
        from google import genai
        from google.genai import types

        try:
            client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
            contents = [
                types.Part.from_bytes(data=clip_bytes, mime_type="video/mp4"),
                prompt,
            ]
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TranscriptPayload,
                temperature=0.0,
            )
            resp = governed(
                model,
                lambda: client.models.generate_content(
                    model=model, contents=contents, config=config
                ),
            )
        except StoryGraphError:
            raise  # governor give-up (QuotaExhausted / TransientModelError), already typed
        except Exception as exc:
            raise StoryGraphError(f"GeminiTranscriber ({model}) failed: {exc}") from exc
        payload = TranscriptPayload.model_validate_json(resp.text or '{"segments": []}')
        return Transcript(segments=payload.segments)
