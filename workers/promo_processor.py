"""Promo job processor — selects highlight moments and stitches them into a promo video."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import deps
from models import PromoSegment

from _promo_helpers import maybe_apply_text_overlays, maybe_prepend_title_card
from base_processor import JobProcessor, TempFileManager

logger = logging.getLogger(__name__)


def _build_promo_segments(segments_raw: list[dict]) -> list[dict]:
    """Convert raw Gemini segment dicts into serialized PromoSegment models."""
    return [
        PromoSegment(
            title=s.get("title", ""),
            description=s.get("description", ""),
            timestamp_start=s.get("timestamp_start", "0:00"),
            timestamp_end=s.get("timestamp_end", "0:00"),
            order=i,
            relevance_score=s.get("relevance_score", 0.0),
        ).dict()
        for i, s in enumerate(segments_raw)
    ]


class PromoProcessor(JobProcessor):
    """Processes pending promo jobs."""

    @property
    def name(self) -> str:
        return "promo"

    @property
    def firestore_update_method(self) -> str:
        return "update_promo_record"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_promo_records(include_archived=False)

    def process(self, record: Any) -> None:
        record_id = record.id
        tmp = TempFileManager()
        try:
            segments_raw = self._analyze_or_resume(record, record_id)
            src_path = self._download_source(record, record_id, tmp)
            segment_paths, segments_raw = self._extract_segments(
                record_id, src_path, segments_raw, tmp
            )
            maybe_prepend_title_card(
                record,
                record_id,
                src_path,
                segments_raw,
                segment_paths,
                tmp,
                self._run_async,
            )
            maybe_apply_text_overlays(
                record,
                record_id,
                src_path,
                segments_raw,
                segment_paths,
                tmp,
                self._run_async,
            )
            output_uri = self._normalize_and_stitch(
                record, record_id, src_path, segment_paths, tmp
            )
            self.update_status(record_id, "completed", 100, output_gcs_uri=output_uri)
            logger.info(
                f"[promo:{record_id}] Completed: {output_uri}",
                extra={
                    "who": "promo",
                    "where": "process",
                    "what": f"completed:{output_uri}",
                    "why": "job_done",
                    "how": "update_status",
                },
            )
        finally:
            tmp.cleanup()

    # ------------------------------------------------------------------
    # Step 1: Gemini analysis (or resume from checkpoint)
    # ------------------------------------------------------------------

    def _analyze_or_resume(self, record: Any, record_id: str) -> list[dict]:
        """Get segments from checkpoint or run Gemini analysis."""
        if record.segments:
            segments_raw = [s.dict() for s in record.segments]
            logger.info(
                f"[promo:{record_id}] Resuming with {len(segments_raw)} segments",
                extra={
                    "who": "promo",
                    "where": "_analyze_or_resume",
                    "what": f"resume:{len(segments_raw)}",
                    "why": "checkpoint_present",
                    "how": "skip_gemini",
                },
            )
            return segments_raw

        self.update_status(record_id, "analyzing", 5)
        logger.info(
            f"[promo:{record_id}] Analyzing video for promo...",
            extra={
                "who": "promo",
                "where": "_analyze_or_resume",
                "what": "start_analysis",
                "why": "no_checkpoint",
                "how": "analyze_video_for_promo",
            },
        )
        result = self._run_async(
            deps.ai_svc.analyze_video_for_promo(
                gcs_uri=record.source_gcs_uri,
                mime_type="video/mp4",
                target_duration=record.target_duration,
                prompt_id=record.prompt_id,
                model_id=getattr(record, "model_id", None),
                region=getattr(record, "region", None),
            )
        )
        segments_raw = result.data.get("segments", [])
        if not segments_raw:
            raise ValueError("Gemini returned no segments")

        segments = _build_promo_segments(segments_raw)
        deps.firestore_svc.update_promo_record(
            record_id, {"segments": segments, "usage": result.usage.dict()}
        )
        logger.info(
            f"[promo:{record_id}] Got {len(segments)} segments",
            extra={
                "who": "promo",
                "where": "_analyze_or_resume",
                "what": f"segments={len(segments)}",
                "why": "analysis_done",
                "how": "update_promo_record",
            },
        )
        return segments

    # ------------------------------------------------------------------
    # Step 2: Download source
    # ------------------------------------------------------------------

    def _download_source(
        self, record: Any, record_id: str, tmp: TempFileManager
    ) -> str:
        self.update_status(record_id, "extracting", 20)
        logger.info(
            f"[promo:{record_id}] Downloading source video...",
            extra={
                "who": "promo",
                "where": "_download_source",
                "what": record.source_gcs_uri,
                "why": "extract_segments",
                "how": "download_to_file",
            },
        )
        src_path = tmp.create(suffix=".mp4")
        deps.storage_svc.download_to_file(record.source_gcs_uri, src_path)
        return src_path

    # ------------------------------------------------------------------
    # Step 3: Extract segments (parallel)
    # ------------------------------------------------------------------

    def _extract_segments(
        self,
        record_id: str,
        src_path: str,
        segments_raw: list[dict],
        tmp: TempFileManager,
    ) -> tuple[list[str], list[dict]]:
        """Extract each segment in parallel, skip failures."""
        from promo_service import extract_segment, parse_timestamp

        tasks = [
            {
                "idx": i,
                "seg": seg,
                "path": tmp.create(suffix=f"_seg{i}.mp4"),
                "start": parse_timestamp(seg["timestamp_start"]),
                "end": parse_timestamp(seg["timestamp_end"]),
            }
            for i, seg in enumerate(segments_raw)
        ]
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(
                    extract_segment, src_path, t["path"], t["start"], t["end"]
                ): t
                for t in tasks
            }
            for future, t in futures.items():
                try:
                    future.result()
                    results.append(t)
                except RuntimeError as e:
                    logger.warning(
                        f"[promo:{record_id}] Skipping segment {t['idx']}: {e}",
                        extra={
                            "who": "promo",
                            "where": "_extract_segments",
                            "what": f"skip_seg:{t['idx']}",
                            "why": str(e),
                            "how": "extract_segment",
                        },
                    )
        results.sort(key=lambda t: t["idx"])
        self.update_status(record_id, "extracting", 50)
        logger.info(
            f"[promo:{record_id}] Extracted {len(results)} segments",
            extra={
                "who": "promo",
                "where": "_extract_segments",
                "what": f"extracted={len(results)}",
                "why": "extraction_done",
                "how": "ThreadPoolExecutor",
            },
        )
        if not results:
            raise ValueError("No valid segments could be extracted")
        return [t["path"] for t in results], [t["seg"] for t in results]

    # ------------------------------------------------------------------
    # Step 4: Normalize, stitch, upload
    # ------------------------------------------------------------------

    def _normalize_and_stitch(
        self,
        record: Any,
        record_id: str,
        src_path: str,
        segment_paths: list[str],
        tmp: TempFileManager,
    ) -> str:
        from ffmpeg_runner import ffprobe_video
        from promo_service import concatenate_with_crossfade

        self.update_status(record_id, "stitching", 55)
        probe = ffprobe_video(src_path)
        tw, th = probe["width"] // 2 * 2, probe["height"] // 2 * 2

        segment_paths = self._normalize_parallel(record_id, segment_paths, tw, th, tmp)
        self.update_status(record_id, "stitching", 60)
        stitched = tmp.create(suffix="_stitched.mp4")
        concatenate_with_crossfade(segment_paths, stitched)
        self.update_status(record_id, "encoding", 85)

        bucket = os.getenv("GCS_BUCKET")
        output_uri = f"gs://{bucket}/promos/{record_id}/final.mp4"
        deps.storage_svc.upload_from_file(stitched, output_uri)
        return output_uri

    def _normalize_parallel(
        self,
        record_id: str,
        segment_paths: list[str],
        tw: int,
        th: int,
        tmp: TempFileManager,
    ) -> list[str]:
        """Normalize all segments to canonical format in parallel."""
        from promo_service import normalize_segment

        tasks = [
            {"idx": i, "src": p, "dest": tmp.create(suffix=f"_norm{i}.mp4")}
            for i, p in enumerate(segment_paths)
        ]
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(normalize_segment, t["src"], t["dest"], tw, th): t
                for t in tasks
            }
            for f, t in futures.items():
                try:
                    f.result()
                    results.append(t)
                except RuntimeError as e:
                    logger.warning(
                        f"[promo:{record_id}] Norm failed for segment {t['idx']}: {e}",
                        extra={
                            "who": "promo",
                            "where": "_normalize_parallel",
                            "what": f"norm_failed:{t['idx']}",
                            "why": str(e),
                            "how": "normalize_segment",
                        },
                    )
        results.sort(key=lambda t: t["idx"])
        logger.info(
            f"[promo:{record_id}] Normalized {len(results)} segments to {tw}x{th}",
            extra={
                "who": "promo",
                "where": "_normalize_parallel",
                "what": f"normalized={len(results)}",
                "why": f"target={tw}x{th}",
                "how": "ThreadPoolExecutor",
            },
        )
        return [t["dest"] for t in results]
