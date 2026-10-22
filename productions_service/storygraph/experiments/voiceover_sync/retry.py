"""Quota-aware retry for experiment Gemini calls (shared project hits TPM 429s)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from ...adapters.transcribe import Transcriber, Transcript
from ...audio.voice.logs import log_ctx
from ...audio.voice.sync import LineSynthesizer
from ...errors import StoryGraphError
from ...schemas.voice import VoiceProfile

T = TypeVar("T")
logger = logging.getLogger(__name__)
BACKOFF_S = (10.0, 20.0, 40.0, 80.0, 120.0)
_TRANSIENT = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "DEADLINE", "EMPTY")


def with_backoff(call: Callable[[], T], what: str) -> T:
    """Run `call`, retrying transient quota/availability errors with fixed backoff."""
    for delay in (*BACKOFF_S, None):
        try:
            return call()
        except StoryGraphError as exc:
            if delay is None or not any(t in str(exc) for t in _TRANSIENT):
                raise
            logger.warning(
                "Transient Gemini error; backing off",
                extra=log_ctx(
                    "experiments.voiceover_sync.retry",
                    "gemini_backoff",
                    str(exc)[:160],
                    f"sleep {delay}s then retry",
                    call=what,
                ),
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


class RetryingTranscriber:
    """`Transcriber` decorator adding quota backoff."""

    def __init__(self, inner: Transcriber) -> None:
        self.inner = inner

    def transcribe(
        self, clip_bytes: bytes, speakers: list[str], lang_hints: list[str]
    ) -> Transcript:
        return with_backoff(
            lambda: self.inner.transcribe(clip_bytes, speakers, lang_hints),
            "transcribe",
        )


class RetryingSynthesizer:
    """`LineSynthesizer` decorator adding quota backoff on top of the adapter's retries."""

    def __init__(self, inner: LineSynthesizer) -> None:
        self.inner = inner

    def synthesize(
        self, text: str, voice: VoiceProfile, lang: str, target_s: float | None
    ) -> bytes:
        return with_backoff(
            lambda: self.inner.synthesize(text, voice, lang, target_s), "tts"
        )
