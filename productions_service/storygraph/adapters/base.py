"""Protocols for ImageGenerator, VideoGenerator, VLMProvider, and TTSProvider."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..compile import Package
from ..config import VideoProviderCfg

T = TypeVar("T", bound=BaseModel)


class ImageGenerator(Protocol):
    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        aspect_ratio: str = "16:9",
        seed: int = 42,
    ) -> bytes: ...


class VideoGenerator(Protocol):
    caps: VideoProviderCfg

    def generate(self, package: Package) -> bytes: ...


class VLMProvider(Protocol):
    def review(
        self,
        images: list[bytes],
        prompt: str,
        schema: type[T],
    ) -> T: ...


class TTSProvider(Protocol):
    def synthesize(self, text: str, voice_profile_id: str) -> bytes: ...
