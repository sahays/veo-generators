"""Clip audio transcription adapter (Gemini audio understanding), cached by content digest."""

from __future__ import annotations

import os
from typing import Protocol

from pydantic import BaseModel, Field

from ..errors import StoryGraphError
from .bounded_cache import BoundedCache, digest


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
        self, model: str = "gemini-3.8-flash", project: str | None = None
    ) -> None:
        self.model = model
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
        result = self._call(clip_bytes, _transcribe_prompt(speakers, lang_hints))
        self._cache.put(key, result)
        return result

    def _call(self, clip_bytes: bytes, prompt: str) -> Transcript:
        from google import genai
        from google.genai import types

        try:
            client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
            resp = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=clip_bytes, mime_type="video/mp4"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Transcript,
                    temperature=0.0,
                ),
            )
        except Exception as exc:
            raise StoryGraphError(
                f"GeminiTranscriber ({self.model}) failed: {exc}"
            ) from exc
        return Transcript.model_validate_json(resp.text or '{"segments": []}')
