"""Dub one language end to end: translate, align, mux, upload.

Sits between the worker (job lifecycle, fan-out) and the three single-purpose
modules it drives — `dubbing_live` (socket), `dubbing_timeline` (alignment
maths), `dubbing_audio` (ffmpeg). `dub_language` never raises: one language
failing must not take the other three down with it, so a failure comes back as
a `failed` variant carrying its reason.
"""

import logging
import os
import tempfile
from typing import Callable

import deps
from dubbing_audio import mux_dub, write_wav
from dubbing_config import OUTPUT_SAMPLE_RATE, supported_languages
from dubbing_live import translate_audio
from dubbing_timeline import assemble_track, build_srt, measure_lag
from models import DubVariant

logger = logging.getLogger(__name__)


def variant_tag(record_id: str, language_code: str) -> str:
    return f"[dub:{record_id}:{language_code}]"


def output_blob_paths(record_id: str, language_code: str) -> tuple[str, str]:
    """Bucket-relative destinations for one language: (mp4, srt).

    Built from the server-generated record id and a language code re-checked
    against the allowlist here — never from a user-supplied filename, so neither
    component can walk out of the `dubs/` prefix. Re-validating rather than
    trusting the router keeps this safe if it is ever called from elsewhere.
    """
    if language_code not in supported_languages():
        raise ValueError(f"unsupported language code: {language_code!r}")
    base = f"dubs/{record_id}/{language_code}"
    return f"{base}.mp4", f"{base}.srt"


async def dub_language(
    record_id: str,
    language_code: str,
    video_path: str,
    pcm: bytes,
    duration_sec: float,
    speech_onset_sec: float,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[DubVariant, str]:
    """Produce the dubbed MP4 and SRT for one target language.

    Returns the variant plus the original-language transcript the session
    reported, which belongs to the record rather than to any one language.
    """
    tag = variant_tag(record_id, language_code)
    variant = DubVariant(language_code=language_code, status="generating")
    source_text = ""
    try:
        result = await translate_audio(pcm, language_code, tag, on_progress=on_progress)
        source_text = "".join(result.source_text).strip()
        if not result.audio:
            raise RuntimeError("Live Translate returned no audio")

        lag = measure_lag(result.first_audio_sec, speech_onset_sec)
        logger.info(
            f"{tag} lag {lag:.2f}s "
            f"(first audio {result.first_audio_sec:.2f}s, onset {speech_onset_sec:.2f}s)"
        )
        if result.usage:
            # Preview pricing is unpublished, so tokens are diagnostics rather
            # than a cost input — logged, not persisted.
            logger.info(
                f"{tag} tokens: prompt={result.usage.get('promptTokenCount')} "
                f"response={result.usage.get('responseTokenCount')}"
            )
        track = assemble_track(result.audio, lag, duration_sec, OUTPUT_SAMPLE_RATE)
        mp4_uri, srt_uri = _publish(
            record_id, language_code, video_path, track, result, lag, duration_sec, tag
        )

        variant.status = "completed"
        variant.output_gcs_uri = mp4_uri
        variant.srt_gcs_uri = srt_uri
        variant.translated_transcript = result.translated_text
        variant.lag_sec = round(lag, 3)
        logger.info(f"{tag} completed → {mp4_uri}")
    except Exception as e:
        variant.status = "failed"
        variant.error_message = str(e)
        logger.error(f"{tag} failed: {e}", exc_info=True)
    return variant, source_text


def _publish(
    record_id, language_code, video_path, track, result, lag, duration_sec, tag
) -> tuple[str, str | None]:
    """Mux the track onto the video and upload the MP4 and its subtitles."""
    mp4_blob, srt_blob = output_blob_paths(record_id, language_code)
    mp4_uri = f"gs://{deps.storage_svc.bucket_name}/{mp4_blob}"
    wav_path = tempfile.mkstemp(suffix=f"_{language_code}.wav")[1]
    mp4_path = tempfile.mkstemp(suffix=f"_{language_code}.mp4")[1]
    try:
        write_wav(track, OUTPUT_SAMPLE_RATE, wav_path)
        mux_dub(video_path, wav_path, mp4_path, tag=tag)
        deps.storage_svc.upload_from_file(mp4_path, mp4_uri, content_type="video/mp4")

        srt = build_srt(result.transcript, lag, duration_sec)
        if not srt:
            logger.warning(f"{tag} no transcript fragments; skipping SRT")
            return mp4_uri, None
        srt_uri = deps.storage_svc.upload_file(
            srt.encode("utf-8"), srt_blob, "application/x-subrip"
        )
        return mp4_uri, srt_uri
    finally:
        for path in (wav_path, mp4_path):
            try:
                os.unlink(path)
            except OSError:
                pass
