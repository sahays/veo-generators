"""Vertex AI Gemini / Imagen adapter (`gemini-nano-banana-2.1`) for reference sheet generation."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types

from ..errors import StoryGraphError
from .governor import EmptyModelResponse, governed


def _extract_inline_image(resp: Any) -> bytes | None:
    """Extract the first inline image payload from a Gemini `GenerateContentResponse`."""
    for cand in resp.candidates or []:
        if not cand.content or not cand.content.parts:
            continue
        for part in cand.content.parts:
            if part.inline_data and part.inline_data.data:
                return bytes(part.inline_data.data)
    return None


class GeminiImageGenerator:
    """Calls Vertex AI Gemini image generation (`gemini-nano-banana-2.1`) strictly without silent fallbacks."""

    def __init__(
        self,
        model: str = "gemini-nano-banana-2.1",
        project: str | None = None,
        location: str | None = None,
    ) -> None:
        self.model = model
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("GEMINI_REGION", "global")

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        aspect_ratio: str = "16:9",
        seed: int = 42,
    ) -> bytes:
        try:
            client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
            contents: list[Any] = [
                types.Part.from_bytes(data=img_bytes, mime_type="image/png")
                for img_bytes in (reference_images or [])
            ]
            contents.append(f"{prompt} (Aspect ratio: {aspect_ratio})")
            config = types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"], seed=seed
            )

            def request() -> bytes:
                resp = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                img_data = _extract_inline_image(resp)
                if img_data is None:
                    raise EmptyModelResponse(
                        f"GeminiImageGenerator ({self.model}) returned no image data "
                        f"for prompt: {prompt[:120]}"
                    )
                return img_data

            return governed(self.model, request)
        except StoryGraphError:
            raise  # already typed: QuotaExhausted / TransientModelError / EmptyModelResponse
        except Exception as exc:
            raise StoryGraphError(
                f"GeminiImageGenerator ({self.model}) failed: {exc}"
            ) from exc
