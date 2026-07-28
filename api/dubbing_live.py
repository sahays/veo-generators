"""Gemini Live Translate session — the only module that talks to the Live API.

Uses a raw WebSocket rather than the google-genai SDK: `types.TranslationConfig`
only exists in google-genai >= 2.8, and `google-adk` pins `google-genai < 2`, so
upgrading would break the ADK agents. The frame shapes below were extracted from
google-genai 2.14's converters, so this sends exactly what the SDK would.
`routers/avatars_live.py` already drives a Live socket the same way.

Two behaviours of this model drive the design, both measured, not assumed:

* Output trails input by ~3.4 s at 1x pacing, so every chunk is stamped with the
  source position consumed when it arrived and the constant offset is removed
  later (`dubbing_timeline.measure_lag`).
* The model never signals completion. After translating it streams silent
  keep-alive audio indefinitely — an unbounded read returned 87 s of audio for a
  30 s clip. A sustained silent run is the only end-of-content signal there is.
"""

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import websockets

from dubbing_config import (
    CHUNK_MS,
    INPUT_SAMPLE_RATE,
    LIVE_URI,
    OUTPUT_SAMPLE_RATE,
    SAMPLE_WIDTH,
    api_key,
    live_model,
    pace,
    silence_floor_db,
    silence_stop_sec,
    window_sec,
)
from dubbing_timeline import AudioChunk, TranscriptEntry, is_silent

logger = logging.getLogger(__name__)

INPUT_BYTES_PER_SEC = INPUT_SAMPLE_RATE * SAMPLE_WIDTH
OUTPUT_BYTES_PER_SEC = OUTPUT_SAMPLE_RATE * SAMPLE_WIDTH
CHUNK_BYTES = INPUT_BYTES_PER_SEC * CHUNK_MS // 1000

# Hard ceiling on one window's drain, in case silence detection never trips
# (e.g. the model streams low-level noise). Generous: the drain normally ends
# a few seconds after the audio does.
DRAIN_TIMEOUT_SEC = 300

# Report streaming progress every N sent chunks (100ms each) — ~2.5s of audio.
PROGRESS_EVERY_N_CHUNKS = 25


@dataclass
class TranslationResult:
    """Everything one or more Live sessions produced for a single language."""

    audio: list[AudioChunk] = field(default_factory=list)
    transcript: list[TranscriptEntry] = field(default_factory=list)
    source_text: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    @property
    def first_audio_sec(self) -> float | None:
        return self.audio[0][0] if self.audio else None

    @property
    def translated_text(self) -> str:
        return "".join(t for _, t in self.transcript).strip()


def build_setup_frame(language_code: str) -> str:
    """First frame on the socket. `echo_target_language` keeps speech that is
    already in the target language audible instead of dropping it to silence,
    so a mixed-language source doesn't come back with holes."""
    return json.dumps(
        {
            "setup": {
                "model": f"models/{live_model()}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "translationConfig": {
                        "target_language_code": language_code,
                        "echo_target_language": True,
                    },
                },
                "inputAudioTranscription": {},
                "outputAudioTranscription": {},
            }
        }
    )


def _audio_frame(chunk: bytes) -> str:
    return json.dumps(
        {
            "realtime_input": {
                "audio": {
                    "data": base64.b64encode(chunk).decode("ascii"),
                    "mimeType": f"audio/pcm;rate={INPUT_SAMPLE_RATE}",
                }
            }
        }
    )


class _WindowSession:
    """One Live socket over one window of audio.

    Sender and receiver run concurrently; `input_pos` is the shared clock that
    links them — the receiver reads whatever position the sender has reached to
    stamp each arriving chunk.
    """

    def __init__(
        self,
        language_code: str,
        offset_sec: float,
        tag: str,
        on_progress: Callable[[float], None] | None = None,
        progress_base_sec: float = 0.0,
        progress_total_sec: float = 0.0,
    ):
        self.language_code = language_code
        self.offset_sec = offset_sec
        self.tag = tag
        self.result = TranslationResult()
        self.input_pos = 0.0
        # Streaming position is the only honest progress signal for this job:
        # the send paces at ~1x realtime, so it accounts for nearly all the
        # wall clock. Reported as a fraction of the *whole* source, not of the
        # current window, so multi-window jobs advance monotonically.
        self._on_progress = on_progress
        self._progress_base_sec = progress_base_sec
        self._progress_total_sec = progress_total_sec
        self._silent_run_bytes = 0
        self._stop_reason = "eof"

    def _report_progress(self) -> None:
        if not self._on_progress or self._progress_total_sec <= 0:
            return
        done = self._progress_base_sec + self.input_pos
        self._on_progress(min(1.0, done / self._progress_total_sec))

    async def run(self, pcm: bytes) -> TranslationResult:
        async with websockets.connect(
            LIVE_URI,
            additional_headers={"x-goog-api-key": api_key()},
            max_size=None,
        ) as ws:
            await ws.send(build_setup_frame(self.language_code))
            receiver = asyncio.create_task(self._receive(ws))
            try:
                await self._send(ws, pcm)
                await asyncio.wait_for(receiver, timeout=DRAIN_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                self._stop_reason = "drain-timeout"
                logger.warning(
                    f"{self.tag} drain exceeded {DRAIN_TIMEOUT_SEC}s; using "
                    f"{len(self.result.audio)} chunks collected so far"
                )
                receiver.cancel()
            finally:
                if not receiver.done():
                    receiver.cancel()
        logger.info(
            f"{self.tag} window done ({self._stop_reason}): "
            f"{len(self.result.audio)} chunks, "
            f"{self._audio_seconds():.1f}s of translated audio"
        )
        return self.result

    def _audio_seconds(self) -> float:
        return sum(len(pcm) for _, pcm in self.result.audio) / OUTPUT_BYTES_PER_SEC

    async def _send(self, ws, pcm: bytes) -> None:
        """Feed the window in 100 ms chunks, paced against a monotonic clock.

        Pacing is anchored to the window start rather than sleeping a fixed
        interval per chunk, so send latency doesn't accumulate into drift over
        the ~600 s of a full window.
        """
        rate = pace()
        started = time.monotonic()
        for index, offset in enumerate(range(0, len(pcm), CHUNK_BYTES)):
            self.input_pos = offset / INPUT_BYTES_PER_SEC
            await ws.send(_audio_frame(pcm[offset : offset + CHUNK_BYTES]))
            # Every ~2.5s of audio, not every 100ms chunk: the callback writes
            # to Firestore and would otherwise stall the socket 10x a second.
            if index % PROGRESS_EVERY_N_CHUNKS == 0:
                self._report_progress()
            due = started + (self.input_pos + CHUNK_MS / 1000) / rate
            nap = due - time.monotonic()
            if nap > 0:
                await asyncio.sleep(nap)
        self.input_pos = len(pcm) / INPUT_BYTES_PER_SEC
        self._report_progress()
        await ws.send(json.dumps({"realtime_input": {"audioStreamEnd": True}}))
        logger.info(f"{self.tag} streamed {self.input_pos:.1f}s at {rate}x")

    async def _receive(self, ws) -> None:
        floor = silence_floor_db()
        stop_bytes = silence_stop_sec() * OUTPUT_BYTES_PER_SEC
        async for raw in ws:
            message = json.loads(raw if isinstance(raw, str) else raw.decode())
            if "setupComplete" in message:
                logger.info(f"{self.tag} session established")
                continue
            if usage := message.get("usageMetadata"):
                self.result.usage = usage
            content = message.get("serverContent")
            if content is None:
                self._log_control_frame(message)
                continue
            self._collect_transcripts(content)
            if self._collect_audio(content, floor, stop_bytes):
                return

    def _log_control_frame(self, message: dict) -> None:
        if "goAway" in message or "error" in message:
            logger.warning(
                f"{self.tag} upstream control frame: {json.dumps(message)[:300]}"
            )

    def _collect_transcripts(self, content: dict) -> None:
        """Record transcript fragments. Text is never logged — it is the user's
        speech, and this runs at INFO in production."""
        stamp = self.input_pos + self.offset_sec
        if text := (content.get("inputTranscription") or {}).get("text"):
            self.result.source_text.append(text)
        if text := (content.get("outputTranscription") or {}).get("text"):
            self.result.transcript.append((stamp, text))

    def _collect_audio(self, content: dict, floor: float, stop_bytes: float) -> bool:
        """Append arriving audio. Returns True when the silent run says the
        model has finished and the socket should be released."""
        stamp = self.input_pos + self.offset_sec
        for part in (content.get("modelTurn") or {}).get("parts") or []:
            inline = part.get("inlineData") or {}
            if not inline.get("data"):
                continue
            pcm = base64.b64decode(inline["data"])
            if not self.result.audio:
                logger.info(f"{self.tag} first translated audio at {stamp:.2f}s")
            self.result.audio.append((stamp, pcm))
            if is_silent(pcm, floor):
                self._silent_run_bytes += len(pcm)
                if self._silent_run_bytes >= stop_bytes:
                    self._stop_reason = "silence"
                    logger.info(
                        f"{self.tag} content ended "
                        f"({silence_stop_sec():.0f}s silence); "
                        f"{len(self.result.audio)} chunks"
                    )
                    return True
            else:
                self._silent_run_bytes = 0
        return False


def split_windows(pcm: bytes) -> list[tuple[float, bytes]]:
    """Slice raw PCM into (offset_sec, bytes) windows under the Live session cap.

    Index arithmetic on the existing buffer — no re-encode, no copy per window
    beyond the slice itself. Boundaries are frame-aligned so a window can never
    start mid-sample.
    """
    span = int(window_sec() * INPUT_SAMPLE_RATE) * SAMPLE_WIDTH
    if span <= 0 or len(pcm) <= span:
        return [(0.0, pcm)]
    return [
        (start / INPUT_BYTES_PER_SEC, pcm[start : start + span])
        for start in range(0, len(pcm), span)
    ]


async def translate_audio(
    pcm: bytes,
    language_code: str,
    tag: str,
    on_progress: Callable[[float], None] | None = None,
) -> TranslationResult:
    """Translate a whole source track, one Live session per window.

    Windows run sequentially: they are consecutive slices of the same audio, and
    the model is a stateful interpreter, so overlapping them would interleave
    two positions of the same conversation.

    `on_progress` receives this language's completion as a 0..1 fraction of the
    whole source, so it stays monotonic across window boundaries.
    """
    windows = split_windows(pcm)
    if len(windows) > 1:
        logger.info(f"{tag} splitting into {len(windows)} session windows")
    total_sec = len(pcm) / INPUT_BYTES_PER_SEC

    combined = TranslationResult()
    for index, (offset, chunk) in enumerate(windows):
        window_tag = tag if len(windows) == 1 else f"{tag}[w{index + 1}/{len(windows)}]"
        session = _WindowSession(
            language_code,
            offset,
            window_tag,
            on_progress=on_progress,
            progress_base_sec=offset,
            progress_total_sec=total_sec,
        )
        result = await session.run(chunk)
        combined.audio.extend(result.audio)
        combined.transcript.extend(result.transcript)
        combined.source_text.extend(result.source_text)
        if result.usage:
            combined.usage = result.usage
    return combined
