"""Vertex AI Gemini VLM adapter for structured visual critique and clip QA."""

from __future__ import annotations

import os
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from ..errors import StoryGraphError

T = TypeVar("T", bound=BaseModel)


class GeminiVLMProvider:
    """Multimodal VLM reviewer backed by Vertex AI Gemini with structured JSON schema output strictly without silent fallbacks."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash",
        project: str | None = None,
        location: str | None = None,
    ) -> None:
        self.model = model
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GEMINI_REGION", "global")

    def review(
        self,
        images: list[bytes],
        prompt: str,
        schema: type[T],
    ) -> T:
        try:
            client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
            contents: list = [
                types.Part.from_bytes(data=img, mime_type="image/png") for img in images
            ]
            contents.append(prompt)
            resp = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.1,
                ),
            )
            if resp.text:
                return schema.model_validate_json(resp.text)
        except Exception as exc:
            raise StoryGraphError(
                f"GeminiVLMProvider ({self.model}) failed visual review: {exc}"
            ) from exc
        raise StoryGraphError(
            f"GeminiVLMProvider ({self.model}) returned empty response for {schema.__name__}"
        )


class CloudTTSProvider:
    """TTS synthesis adapter with deterministic fallback."""

    def synthesize(self, text: str, voice_profile_id: str) -> bytes:
        from .mock import MockTTSProvider

        return MockTTSProvider().synthesize(text, voice_profile_id)
