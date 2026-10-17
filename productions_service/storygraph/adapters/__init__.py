"""Provider adapters for ImageGenerator, VideoGenerator, VLM, TTS, and Media Frame Extraction."""

from .base import ImageGenerator, TTSProvider, VideoGenerator, VLMProvider
from .gemini_image import GeminiImageGenerator
from .gemini_video import GeminiVideoGenerator
from .media_frames import extract_representative_frames_png
from .mock import (
    MockImageGenerator,
    MockLLMClient,
    MockTTSProvider,
    MockVideoGenerator,
    MockVLMProvider,
)
from .tts import CloudTTSProvider
from .vlm import GeminiVLMProvider

__all__ = [
    "CloudTTSProvider",
    "GeminiImageGenerator",
    "GeminiVLMProvider",
    "GeminiVideoGenerator",
    "ImageGenerator",
    "MockImageGenerator",
    "MockLLMClient",
    "MockTTSProvider",
    "MockVLMProvider",
    "MockVideoGenerator",
    "TTSProvider",
    "VLMProvider",
    "VideoGenerator",
    "extract_representative_frames_png",
]
