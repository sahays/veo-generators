"""Audio I/O for dubbing — every ffmpeg/ffprobe call the feature makes.

Kept apart from `dubbing_timeline` (pure maths) and `dubbing_live` (the socket)
so the parts that need a subprocess are in one small, obvious place. All
commands go through `ffmpeg_runner`, which passes argv as a list — never a
shell string — so a filename can never be interpreted as arguments.
"""

import logging
import os
import re
import tempfile
import wave

from dubbing_config import INPUT_SAMPLE_RATE, SAMPLE_WIDTH
from ffmpeg_runner import run_ffmpeg, run_ffmpeg_probe
from diarization_service import extract_audio

logger = logging.getLogger(__name__)

# ffmpeg's silencedetect prints "silence_end: <sec> | silence_duration: <sec>".
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")


def extract_source_pcm(video_path: str, tag: str = "") -> str:
    """Extract the source audio as raw 16 kHz mono s16le — what Live wants.

    Reuses `diarization_service.extract_audio`, which already produces exactly
    that as a WAV, then unwraps the container. Reading frames through `wave`
    rather than slicing a fixed 44-byte header keeps this correct when ffmpeg
    emits extra chunks (LIST/INFO), which would otherwise prepend metadata
    bytes to the audio and desync every stamp downstream.
    """
    wav_path = extract_audio(video_path)
    try:
        with wave.open(wav_path, "rb") as wav:
            if (wav.getframerate(), wav.getnchannels()) != (INPUT_SAMPLE_RATE, 1):
                raise RuntimeError(
                    f"expected {INPUT_SAMPLE_RATE} Hz mono, got "
                    f"{wav.getframerate()} Hz / {wav.getnchannels()}ch"
                )
            pcm = wav.readframes(wav.getnframes())
        fd, raw_path = tempfile.mkstemp(suffix=".raw")
        with os.fdopen(fd, "wb") as out:
            out.write(pcm)
        logger.info(
            f"{tag} extracted {len(pcm) / (INPUT_SAMPLE_RATE * SAMPLE_WIDTH):.1f}s "
            f"of 16kHz mono PCM"
        )
        return raw_path
    finally:
        _safe_unlink(wav_path)


def first_speech_onset(video_path: str, floor_db: int = -35, tag: str = "") -> float:
    """Source time of the first non-silent audio, via ffmpeg silencedetect.

    This is the anchor the interpreter lag is measured against: the gap between
    the first thing said and the first thing translated. Returns 0.0 when the
    audio starts loud (no leading silence) or when detection fails — both mean
    "assume speech starts at the top", which is the safe default.
    """
    cmd = [
        "ffmpeg",
        "-i",
        video_path,
        "-af",
        f"silencedetect=n={floor_db}dB:d=0.3",
        "-f",
        "null",
        "-",
    ]
    stderr = run_ffmpeg_probe(cmd, timeout=300, label=f"{tag} silencedetect".strip())
    if not stderr:
        logger.warning(f"{tag} silencedetect produced nothing; assuming onset 0.0s")
        return 0.0

    # Leading silence only: a silence_start at ~0 followed by a silence_end.
    starts = [float(m) for m in _SILENCE_START_RE.findall(stderr)]
    ends = [float(m) for m in _SILENCE_END_RE.findall(stderr)]
    if not ends or not starts or starts[0] > 0.5:
        logger.info(f"{tag} no leading silence; speech onset 0.0s")
        return 0.0
    logger.info(f"{tag} speech onset {ends[0]:.2f}s (leading silence trimmed)")
    return ends[0]


def write_wav(pcm: bytes, sample_rate: int, path: str) -> str:
    """Wrap raw mono s16le PCM in a WAV container so ffmpeg can read it without
    being told the format on the command line."""
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return path


def mux_dub(video_path: str, dub_wav_path: str, out_path: str, tag: str = "") -> str:
    """Replace the source audio with the dubbed track in a single pass.

    Video is stream-copied — the picture is untouched, so this is fast and
    lossless. `-shortest` is belt-and-braces: `assemble_track` already returns
    a track of exactly the video's duration.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-i",
        dub_wav_path,
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        out_path,
    ]
    run_ffmpeg(cmd, timeout=900, label=f"{tag} mux-dub".strip())
    return out_path


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
