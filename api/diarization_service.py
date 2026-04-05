"""Speaker diarization service using Google Cloud Speech V2 (Chirp 3).

Handles long audio (>20 min) by splitting into chunks, processing in
parallel threads, and merging results with cross-boundary continuity.
"""

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from google.api_core import exceptions as google_exceptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech

from ffmpeg_runner import ffprobe_duration, run_ffmpeg

logger = logging.getLogger(__name__)

MAX_CHUNK_DURATION = 1200  # 20 minutes — Chirp 3 BatchRecognize limit
MAX_WORKERS = 4


class DiarizationService:
    """Wraps Google Cloud Speech V2 for speaker diarization via Chirp 3."""

    def __init__(self, project_id: str, location: str = "us-central1"):
        self.project_id = project_id
        self.location = location
        api_endpoint = f"{location}-speech.googleapis.com"
        self.client = SpeechClient(
            client_options={"api_endpoint": api_endpoint},
        )
        self.recognizer = f"projects/{project_id}/locations/{location}/recognizers/_"

    def transcribe_with_diarization(
        self,
        audio_gcs_uri: str,
        speaker_count_hint: int = 2,
        model: str = "chirp_3",
        storage_svc=None,
        record_id: str = "",
        audio_duration: float | None = None,
    ) -> dict:
        """Run Chirp 3 transcription with speaker diarization.

        For audio >20 min, splits into chunks and processes in parallel.
        """
        tag = f"[chirp:{record_id}]" if record_id else "[chirp]"
        duration = audio_duration
        if duration is None:
            duration = _probe_gcs_duration(audio_gcs_uri, storage_svc, tag)
        else:
            logger.info(f"{tag} Audio duration (from caller): {duration:.0f}s")

        if duration is not None and duration > MAX_CHUNK_DURATION:
            logger.info(f"{tag} Audio {duration:.0f}s, chunking required")
            return self._transcribe_chunked(
                audio_gcs_uri,
                duration,
                speaker_count_hint,
                model,
                storage_svc,
                tag,
            )

        logger.info(f"{tag} Processing single file: {audio_gcs_uri}")
        return self._transcribe_single(audio_gcs_uri, speaker_count_hint, model, tag)

    def _transcribe_single(
        self,
        audio_gcs_uri: str,
        speaker_count_hint: int,
        model: str,
        tag: str,
    ) -> dict:
        """Transcribe a single audio file (must be ≤20 min)."""
        config = _build_recognition_config(model, speaker_count_hint)
        logger.info(f"{tag} Chirp 3 request: uri={audio_gcs_uri}")

        try:
            request = cloud_speech.BatchRecognizeRequest(
                recognizer=self.recognizer,
                config=config,
                files=[cloud_speech.BatchRecognizeFileMetadata(uri=audio_gcs_uri)],
                recognition_output_config=cloud_speech.RecognitionOutputConfig(
                    inline_response_config=cloud_speech.InlineOutputConfig(),
                ),
            )
            operation = self.client.batch_recognize(request=request)
            logger.info(f"{tag} Waiting for batch recognition...")
            response = operation.result(timeout=600)
            result = _parse_response(response, audio_gcs_uri, tag)
            logger.info(f"{tag} Complete: {len(result['speaker_segments'])} segments")
            return result
        except google_exceptions.InvalidArgument as e:
            logger.error(f"{tag} Invalid argument: {e}")
            raise
        except Exception as e:
            logger.error(f"{tag} Failed for {audio_gcs_uri}: {e}")
            raise

    def _transcribe_chunked(
        self,
        audio_gcs_uri: str,
        duration: float,
        speaker_count_hint: int,
        model: str,
        storage_svc,
        tag: str,
    ) -> dict:
        """Split long audio, transcribe chunks in parallel, merge."""
        if not storage_svc:
            raise RuntimeError("storage_svc required for chunked diarization")

        tmp_audio = tempfile.mkstemp(suffix=".wav")[1]
        chunk_paths = []
        try:
            storage_svc.download_to_file(audio_gcs_uri, tmp_audio)
            chunk_uris, chunk_offsets, chunk_paths = _split_and_upload_chunks(
                tmp_audio,
                audio_gcs_uri,
                duration,
                storage_svc,
                tag,
            )
            results = self._dispatch_parallel(
                chunk_uris,
                speaker_count_hint,
                model,
                tag,
            )
            return _merge_chunk_results(results, chunk_offsets, tag)
        finally:
            for p in [tmp_audio] + chunk_paths:
                _safe_unlink(p)

    def _dispatch_parallel(
        self,
        chunk_uris: list,
        speaker_count_hint: int,
        model: str,
        tag: str,
    ) -> list:
        """Transcribe multiple chunks in parallel threads."""
        n = len(chunk_uris)
        results = [None] * n
        workers = min(n, MAX_WORKERS)
        logger.info(f"{tag} Processing {n} chunks with {workers} threads")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    self._transcribe_single,
                    uri,
                    speaker_count_hint,
                    model,
                    f"{tag}[chunk:{i + 1}/{n}]",
                ): i
                for i, uri in enumerate(chunk_uris)
            }
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()
                logger.info(
                    f"{tag} Chunk {idx + 1}/{n}: "
                    f"{len(results[idx]['speaker_segments'])} segments"
                )
        return results


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------


def extract_audio(video_path: str, output_path: str | None = None) -> str:
    """Extract audio from video as mono 16kHz WAV."""
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        output_path,
    ]
    run_ffmpeg(cmd, timeout=300, label="extract-audio")
    size = os.path.getsize(output_path)
    logger.info(f"Audio extracted: {output_path} ({size} bytes)")
    return output_path


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------


def _split_and_upload_chunks(
    tmp_audio: str,
    audio_gcs_uri: str,
    duration: float,
    storage_svc,
    tag: str,
) -> tuple:
    """Split audio into ≤20-min chunks, upload each to GCS."""
    num = int(duration // MAX_CHUNK_DURATION) + (
        1 if duration % MAX_CHUNK_DURATION > 0 else 0
    )
    logger.info(f"{tag} Splitting into {num} chunks of ≤{MAX_CHUNK_DURATION}s")
    base = audio_gcs_uri.rsplit("/", 1)[0]

    chunk_paths, chunk_uris, chunk_offsets = [], [], []
    for i in range(num):
        start = i * MAX_CHUNK_DURATION
        end = min((i + 1) * MAX_CHUNK_DURATION, duration)
        path = tempfile.mkstemp(suffix=f"_chunk{i}.wav")[1]
        chunk_paths.append(path)
        chunk_offsets.append(start)

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            tmp_audio,
            "-t",
            f"{end - start:.3f}",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            path,
        ]
        run_ffmpeg(cmd, timeout=120, label=f"split-chunk-{i}")

        uri = f"{base}/audio_chunk{i}.wav"
        chunk_uris.append(uri)
        storage_svc.upload_from_file(path, uri)
        logger.info(f"{tag} Chunk {i + 1}/{num}: {start:.0f}s-{end:.0f}s → {uri}")

    return chunk_uris, chunk_offsets, chunk_paths


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _build_recognition_config(model: str, speaker_count_hint: int):
    """Build Chirp 3 RecognitionConfig with diarization."""
    return cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=["auto"],
        model=model,
        features=cloud_speech.RecognitionFeatures(
            diarization_config=cloud_speech.SpeakerDiarizationConfig(
                min_speaker_count=max(1, speaker_count_hint - 1),
                max_speaker_count=max(2, speaker_count_hint + 2),
            ),
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
        ),
    )


def _parse_response(response, uri: str, tag: str) -> dict:
    """Parse BatchRecognize response into speaker segments."""
    result = response.results.get(uri)
    if not result:
        for key, val in response.results.items():
            logger.info(f"{tag} Result key mismatch, using: {key}")
            result = val
            break

    _log_response_errors(result, tag)
    if not result or not result.transcript or not result.transcript.results:
        logger.warning(f"{tag} No transcript results")
        return {"speaker_segments": [], "transcript": ""}

    segments, transcripts = [], []
    for res in result.transcript.results:
        if not res.alternatives:
            continue
        alt = res.alternatives[0]
        transcripts.append(alt.transcript)
        segments.extend(_extract_word_segments(alt.words))

    merged = _merge_adjacent_segments(segments)
    logger.info(
        f"{tag} Parsed: {len(merged)} segments, "
        f"{len(set(s['speaker_id'] for s in merged))} speakers"
    )
    return {"speaker_segments": merged, "transcript": " ".join(transcripts)}


def _log_response_errors(result, tag: str) -> None:
    """Log any errors in the recognition result."""
    if not result:
        return
    has_err = hasattr(result, "error") and result.error and result.error.code != 0
    if has_err:
        logger.warning(
            f"{tag} Chirp 3 error: code={result.error.code}, msg={result.error.message}"
        )


def _extract_word_segments(words) -> list:
    """Build speaker segments from word-level speaker tags."""
    segments = []
    current_speaker = None
    seg_start = None

    for word in words:
        raw = word.speaker_label or str(word.speaker_tag)
        speaker = f"Speaker {raw}" if not raw.startswith("Speaker") else raw
        if speaker != current_speaker:
            if current_speaker is not None and seg_start is not None:
                segments.append(
                    {
                        "speaker_id": current_speaker,
                        "start_sec": seg_start,
                        "end_sec": _duration_to_sec(word.start_offset),
                        "confidence": 0.9,
                    }
                )
            current_speaker = speaker
            seg_start = _duration_to_sec(word.start_offset)

    if current_speaker is not None and seg_start is not None:
        segments.append(
            {
                "speaker_id": current_speaker,
                "start_sec": seg_start,
                "end_sec": _duration_to_sec(words[-1].end_offset),
                "confidence": 0.9,
            }
        )
    return segments


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _probe_gcs_duration(gcs_uri: str, storage_svc, tag: str) -> float | None:
    """Download audio from GCS, probe duration, return seconds or None."""
    if not storage_svc:
        return None
    tmp = None
    try:
        tmp = tempfile.mkstemp(suffix=".wav")[1]
        storage_svc.download_to_file(gcs_uri, tmp)
        dur = ffprobe_duration(tmp)
        logger.info(f"{tag} Audio duration: {dur:.0f}s")
        return dur
    except Exception as e:
        logger.warning(f"{tag} Could not determine duration: {e}")
        return None
    finally:
        if tmp:
            _safe_unlink(tmp)


def _duration_to_sec(duration) -> float:
    """Convert protobuf Duration to seconds."""
    if duration is None:
        return 0.0
    if hasattr(duration, "total_seconds"):
        return duration.total_seconds()
    return float(duration.seconds) + float(duration.nanos) / 1e9


def _merge_adjacent_segments(segments: list) -> list:
    """Merge consecutive segments from the same speaker."""
    if not segments:
        return segments
    merged = [segments[0].copy()]
    for seg in segments[1:]:
        if seg["speaker_id"] == merged[-1]["speaker_id"]:
            merged[-1]["end_sec"] = seg["end_sec"]
        else:
            merged.append(seg.copy())
    return merged


def _merge_chunk_results(results: list, chunk_offsets: list, tag: str) -> dict:
    """Merge diarization results from multiple chunks with time offsets.

    Each chunk's speaker IDs are prefixed with the chunk index (e.g.
    "C1 Speaker 2") because Chirp assigns IDs independently per chunk —
    "Speaker 1" in chunk A is not the same person as "Speaker 1" in chunk B.
    Single-chunk results keep IDs unprefixed for cleaner output.
    """
    multi = len(results) > 1
    all_segments, all_transcripts = [], []
    for ci, (result, offset) in enumerate(zip(results, chunk_offsets)):
        for seg in result.get("speaker_segments", []):
            sid = f"C{ci + 1} {seg['speaker_id']}" if multi else seg["speaker_id"]
            all_segments.append(
                {
                    "speaker_id": sid,
                    "start_sec": seg["start_sec"] + offset,
                    "end_sec": seg["end_sec"] + offset,
                    "confidence": seg.get("confidence", 0.9),
                }
            )
        t = result.get("transcript", "")
        if t:
            all_transcripts.append(t)

    merged = _merge_adjacent_segments(all_segments)
    speakers = len(set(s["speaker_id"] for s in merged)) if merged else 0
    logger.info(
        f"{tag} Merged {len(results)} chunks: {len(merged)} segments, {speakers} speakers"
    )
    return {"speaker_segments": merged, "transcript": " ".join(all_transcripts)}


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
