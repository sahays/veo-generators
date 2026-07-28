"""Dubbing job processor — one source video, one dubbed MP4 per language."""

import logging
import os
import time

import deps
from base_processor import JobProcessor, TempFileManager, resolve_variant_status
from dubbing_audio import extract_source_pcm, first_speech_onset
from dubbing_config import max_source_minutes
from dubbing_service import dub_language
from ffmpeg_runner import ffprobe_video

logger = logging.getLogger(__name__)

# Progress band reserved for the dubbing phase. Below it: download, extract,
# onset probe. Above it: the final Firestore write at 100.
PROGRESS_FLOOR = 15
PROGRESS_CEILING = 95
# Minimum gap between streaming-progress writes, so a Firestore round-trip
# can't stall the Live socket it is reporting on.
PROGRESS_WRITE_INTERVAL_SEC = 5.0


class DubbingProcessor(JobProcessor):
    """Streams the source audio through Gemini Live Translate once per target
    language and muxes each translated track back onto the video."""

    @property
    def name(self) -> str:
        return "dubbing"

    @property
    def firestore_update_method(self) -> str:
        return "update_dub_record"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_dub_records(include_archived=False)

    def process(self, record) -> None:
        record_id = record.id
        tag = f"[dub:{record_id}]"
        variants = [v.dict() for v in record.variants]
        if not variants:
            self.mark_failed(record_id, "No target languages selected")
            return

        self.update_status(record_id, "generating", 5)
        tmp = TempFileManager()
        try:
            video_path, probe = self._fetch_source(record, tag, tmp)
            pcm_path = tmp.track(extract_source_pcm(video_path, tag))
            onset = first_speech_onset(video_path, tag=tag)
            self.update_status(
                record_id,
                "generating",
                PROGRESS_FLOOR,
                duration_sec=probe["duration"],
            )

            results = self._run_async(
                self._dub_each_language(
                    record_id, variants, video_path, pcm_path, probe, onset
                )
            )
            self._finalize(record_id, record, variants, results, probe, tag)
        except Exception as e:
            logger.error(f"{tag} failed: {e}", exc_info=True)
            self.mark_failed(record_id, str(e))
        finally:
            tmp.cleanup()

    # ------------------------------------------------------------------
    # Source acquisition
    # ------------------------------------------------------------------

    def _fetch_source(self, record, tag: str, tmp: TempFileManager) -> tuple[str, dict]:
        """Download the source and validate it can actually be dubbed.

        The bucket check is defensive: `source_gcs_uri` reaches the worker via
        Firestore, so a hand-edited document must not be able to point the
        downloader at another bucket.
        """
        bucket_prefix = f"gs://{deps.storage_svc.bucket_name}/"
        if not record.source_gcs_uri.startswith(bucket_prefix):
            raise ValueError("source_gcs_uri is outside this service's bucket")

        video_path = tmp.create(suffix=".mp4")
        deps.storage_svc.download_to_file(record.source_gcs_uri, video_path)
        probe = ffprobe_video(video_path)
        if not probe["has_audio"]:
            raise ValueError("Source video has no audio track to dub")

        limit_sec = max_source_minutes() * 60
        if probe["duration"] > limit_sec:
            raise ValueError(
                f"Source is {probe['duration'] / 60:.1f} min; the limit is "
                f"{max_source_minutes():.0f} min"
            )
        logger.info(
            f"{tag} source {probe['duration']:.1f}s "
            f"{probe['width']}x{probe['height']} downloaded"
        )
        return video_path, probe

    # ------------------------------------------------------------------
    # Fan-out
    # ------------------------------------------------------------------

    async def _dub_each_language(
        self, record_id, variants, video_path, pcm_path, probe, onset
    ) -> list:
        """Dub each pending language in turn, publishing results as they land.

        Sequential rather than concurrent: running all four at once finished
        them within a second of each other at the very end, so the record sat
        untouched for the whole job and nothing was watchable until everything
        was. One at a time costs N passes of wall clock (the send paces at ~1x
        realtime) but each language is uploaded and visible as soon as it is
        done, and progress reflects real position in the work.
        """
        with open(pcm_path, "rb") as f:
            pcm = f.read()
        pending = [
            i for i, v in enumerate(variants) if v["status"] in ("pending", "failed")
        ]

        results = []
        for step, index in enumerate(pending):
            variants[index] = {**variants[index], "status": "generating"}
            self._write_progress(record_id, variants, step, 0.0, len(pending))
            variant, source_text = await dub_language(
                record_id,
                variants[index]["language_code"],
                video_path,
                pcm,
                probe["duration"],
                onset,
                on_progress=self._progress_reporter(
                    record_id, variants, step, len(pending)
                ),
            )
            variants[index] = variant.dict()
            results.append((index, (variant, source_text)))
            self._write_progress(record_id, variants, step + 1, 0.0, len(pending))
        return results

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def _progress_reporter(self, record_id, variants, step, total):
        """Throttled callback handed to the Live sender.

        Streaming is ~all of a language's wall clock, so without this the record
        would not move for minutes at a time. Writes are rate-limited because
        the callback fires from inside the send loop and a Firestore round-trip
        there stalls the socket.
        """
        last = [0.0]

        def report(fraction: float) -> None:
            now = time.monotonic()
            if now - last[0] < PROGRESS_WRITE_INTERVAL_SEC:
                return
            last[0] = now
            self._write_progress(record_id, variants, step, fraction, total)

        return report

    def _write_progress(self, record_id, variants, step, fraction, total) -> None:
        """Map (language index, position within it) onto the 15-95% band."""
        if total <= 0:
            return
        done = min(1.0, (step + fraction) / total)
        pct = PROGRESS_FLOOR + int(done * (PROGRESS_CEILING - PROGRESS_FLOOR))
        deps.firestore_svc.update_dub_record(
            record_id, {"variants": variants, "progress_pct": pct}
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _finalize(self, record_id, record, variants, results, probe, tag) -> None:
        """Write variant outcomes, the source transcript, usage and rollup."""
        source_text = ""
        for index, (variant, session_source_text) in results:
            variants[index] = variant.dict()
            # Identical across languages — the first session to report it wins.
            source_text = source_text or session_source_text

        status = resolve_variant_status(variants)
        updates = {
            "variants": variants,
            "status": status,
            "progress_pct": 100,
            "duration_sec": probe["duration"],
            "usage": self._merge_usage(record, variants, probe),
        }
        if source_text:
            updates["source_transcript"] = source_text
        self._set_completion_timestamp(updates, status)
        deps.firestore_svc.update_dub_record(record_id, updates)

        completed = sum(1 for v in variants if v["status"] == "completed")
        logger.info(f"{tag} {status}: {completed}/{len(variants)} languages dubbed")

    @staticmethod
    def _merge_usage(record, variants, probe) -> dict:
        """Record dubbed minutes as a fact; cost is recomputed from it by
        `/pricing/usage` against current rates."""
        usage = record.usage.dict()
        dubbed = sum(1 for v in variants if v["status"] == "completed")
        minutes = (probe["duration"] / 60.0) * dubbed
        usage["dub_minutes"] = usage.get("dub_minutes", 0.0) + round(minutes, 3)
        usage["model_name"] = os.getenv(
            "DUBBING_LIVE_MODEL", "gemini-3.5-live-translate-preview"
        )
        usage["pricing_confidence"] = "low"
        usage["pricing_notes"] = "Live Translate preview pricing is not published"
        return usage
