"""Dubbing timeline assembly — pure functions, no I/O and no SDK.

Live Translate is a simultaneous interpreter: translated speech trails the input
by a few seconds (measured ~3.4 s at 1x pacing) and arrives as a stream of PCM
chunks rather than a finished track. Turning that into an audio track that can
be muxed onto the source video is three decisions:

1. how far to shift the stream left so speech lands under the mouth that said it
   (`measure_lag`),
2. where each chunk belongs on a fixed-length timeline (`assemble_track`),
3. the same shift applied to the transcript for subtitles (`build_srt`).

Kept free of I/O so it is unit-testable without credentials, ffmpeg, or a
network — and so segment-aligned fitting can later replace `assemble_track`
without touching the worker.
"""

import array
import math
from typing import Iterable, Sequence

# One stamped chunk of translated audio: (source_time_sec, pcm_bytes).
AudioChunk = tuple[float, bytes]
# One stamped fragment of output transcript: (source_time_sec, text).
TranscriptEntry = tuple[float, str]


def measure_lag(first_output_sec: float | None, speech_onset_sec: float) -> float:
    """Interpreter lag: how long after the first source speech the first
    translated audio appeared.

    Both arguments are positions on the *source* timeline, so their difference
    is the constant offset to remove. Clamped at zero — an output that appears
    to precede the speech that caused it means the onset probe was fooled (music
    under the intro, say), and shifting right would only make it worse.
    """
    if first_output_sec is None:
        return 0.0
    return max(0.0, first_output_sec - speech_onset_sec)


def assemble_track(
    chunks: Iterable[AudioChunk],
    lag_sec: float,
    duration_sec: float,
    sample_rate: int,
    sample_width: int = 2,
) -> bytes:
    """Lay stamped chunks onto a silent timeline of exactly `duration_sec`.

    Single pass, O(total bytes): the buffer is preallocated at its final size
    and each chunk is copied into a slice. Accumulating with `buf += chunk`
    would reallocate and recopy on every one of thousands of chunks.

    A monotonic write cursor makes the placement total: a chunk starts at its
    stamp, or at the end of the previous chunk if that is later. Chunks
    therefore never overwrite each other, so no speech is truncated when the
    interpreter emits faster than the stamps advance — the common case, since
    stamps only move when the sender feeds more input. Trailing audio that would
    run past the video is dropped rather than extending the track: the mux
    depends on the returned length matching the video exactly.
    """
    frame = sample_width
    total = int(duration_sec * sample_rate) * frame
    if total <= 0:
        return b""
    buf = bytearray(total)  # zero-filled == PCM silence
    cursor = 0
    for stamp, pcm in chunks:
        if not pcm:
            continue
        # Round to a whole frame so a shift can never split a sample and turn
        # the rest of the track into noise.
        want = int(max(0.0, stamp - lag_sec) * sample_rate) * frame
        start = max(want, cursor)
        if start >= total:
            break  # stamps are non-decreasing; nothing later can fit either
        end = min(start + len(pcm), total)
        buf[start:end] = pcm[: end - start]
        cursor = end
    return bytes(buf)


def is_silent(pcm: bytes, floor_db: float, sample_width: int = 2) -> bool:
    """True when a chunk carries no signal above `floor_db` (dBFS).

    The end-of-content signal for a Live Translate session: the model sends no
    completion flag, it just switches to streaming silence. RMS is computed over
    an `array` view of the whole chunk rather than a per-sample Python loop,
    because this runs on every chunk of every language.
    """
    samples = array.array("h")
    if sample_width != 2 or len(pcm) < sample_width:
        return not pcm
    samples.frombytes(pcm[: len(pcm) - len(pcm) % sample_width])
    if not samples:
        return True
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms <= 0:
        return True
    return 20 * math.log10(rms / 32768) < floor_db


def _timecode(seconds: float) -> str:
    """SRT timecode: HH:MM:SS,mmm."""
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(
    entries: Sequence[TranscriptEntry],
    lag_sec: float,
    duration_sec: float,
    min_cue_sec: float = 1.2,
    max_chars: int = 84,
) -> str:
    """Render stamped transcript fragments as SRT, shifted by the same lag.

    The model emits transcript in short fragments — often two or three words,
    a few hundred milliseconds apart. Rendering one cue per fragment gives
    sub-second flicker, and padding each to a readable length makes cues
    *overlap*, which players stack on top of each other.

    So this groups first, then renders: consecutive fragments merge until the
    group spans `min_cue_sec` or would exceed `max_chars`, and every cue then
    ends exactly where the next begins. Overlap is impossible by construction
    rather than by clamping. Both passes are O(n).
    """
    cues = [
        (max(0.0, stamp - lag_sec), text.strip())
        for stamp, text in entries
        if text and text.strip()
    ]
    if not cues:
        return ""

    groups: list[list] = []
    for start, text in cues:
        if groups:
            open_start, open_text = groups[-1]
            merged = f"{open_text} {text}".strip()
            if start - open_start < min_cue_sec and len(merged) <= max_chars:
                groups[-1][1] = merged
                continue
        groups.append([start, text])

    blocks = []
    for i, (start, text) in enumerate(groups):
        end = min(
            groups[i + 1][0] if i + 1 < len(groups) else duration_sec, duration_sec
        )
        if end <= start:
            continue
        blocks.append(
            f"{len(blocks) + 1}\n{_timecode(start)} --> {_timecode(end)}\n{text}\n"
        )
    return "\n".join(blocks)
