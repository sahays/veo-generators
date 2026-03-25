"""
Promo job processor — selects highlight moments and stitches them into a promo video.
"""

import asyncio
import logging
import os
import time

import deps
from models import PromoSegment

from base_processor import JobProcessor, TempFileManager

logger = logging.getLogger(__name__)


class PromoProcessor(JobProcessor):
    """Processes pending promo jobs."""

    @property
    def name(self) -> str:
        return "promo"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_promo_records(include_archived=False)

    def update_status(
        self, record_id: str, status: str, progress: int, **extra
    ) -> None:
        updates = {"status": status, "progress_pct": progress, **extra}
        self._set_completion_timestamp(updates, status)
        deps.firestore_svc.update_promo_record(record_id, updates)

    def mark_failed(self, record_id: str, error_message: str) -> None:
        self.update_status(record_id, "failed", 0, error_message=error_message)

    def process(self, record) -> None:
        from promo_service import (
            parse_timestamp,
            extract_segment,
            concatenate_with_crossfade,
        )

        record_id = record.id
        tmp = TempFileManager()

        try:
            # --- Step 1: Gemini selects moments ---
            self.update_status(record_id, "analyzing", 5)
            logger.info(f"[promo:{record_id}] Analyzing video for promo...")

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    deps.ai_svc.analyze_video_for_promo(
                        gcs_uri=record.source_gcs_uri,
                        mime_type="video/mp4",
                        target_duration=record.target_duration,
                        prompt_id=record.prompt_id,
                    )
                )
            finally:
                loop.close()

            segments_raw = result.data.get("segments", [])
            if not segments_raw:
                raise ValueError("Gemini returned no segments for this theme")

            # Save segments and usage
            segments = [
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
            deps.firestore_svc.update_promo_record(
                record_id,
                {"segments": segments, "usage": result.usage.dict()},
            )
            logger.info(f"[promo:{record_id}] Got {len(segments_raw)} segments")

            # --- Step 2: Download source video ---
            self.update_status(record_id, "extracting", 20)
            logger.info(f"[promo:{record_id}] Downloading source video...")

            src_path = tmp.create(suffix=".mp4")
            deps.storage_svc.download_to_file(record.source_gcs_uri, src_path)
            logger.info(f"[promo:{record_id}] Downloaded to {src_path}")

            # --- Step 3: Extract each segment ---
            segment_paths = []
            for i, seg in enumerate(segments_raw):
                start_sec = parse_timestamp(seg["timestamp_start"])
                end_sec = parse_timestamp(seg["timestamp_end"])

                seg_path = tmp.create(suffix=f"_seg{i}.mp4")
                extract_segment(src_path, seg_path, start_sec, end_sec)
                segment_paths.append(seg_path)

                progress = 20 + int((i + 1) / len(segments_raw) * 30)
                self.update_status(record_id, "extracting", progress)

            logger.info(f"[promo:{record_id}] Extracted {len(segment_paths)} segments")

            # --- Step 3b: Generate thumbnail title card ---
            if record.generate_thumbnail:
                self._generate_title_card(
                    record, record_id, src_path, segments_raw, segment_paths, tmp
                )

            # --- Step 3c: Generate text overlays ---
            if record.text_overlay:
                self._apply_text_overlays(
                    record, record_id, src_path, segments_raw, segment_paths, tmp
                )

            # --- Step 4: Concatenate with cross-dissolve ---
            self.update_status(record_id, "stitching", 55)
            logger.info(f"[promo:{record_id}] Stitching with cross-dissolve...")

            stitched_path = tmp.create(suffix="_stitched.mp4")
            concatenate_with_crossfade(segment_paths, stitched_path)
            self.update_status(record_id, "stitching", 70)

            # --- Step 5: Upload final to GCS ---
            self.update_status(record_id, "encoding", 85)
            logger.info(f"[promo:{record_id}] Uploading final video...")
            bucket = os.getenv("GCS_BUCKET")
            output_uri = f"gs://{bucket}/promos/{record_id}/final.mp4"
            deps.storage_svc.upload_from_file(stitched_path, output_uri)

            # --- Step 6: Done ---
            self.update_status(record_id, "completed", 100, output_gcs_uri=output_uri)
            logger.info(f"[promo:{record_id}] Completed: {output_uri}")

        finally:
            tmp.cleanup()

    def _generate_title_card(
        self,
        record,
        record_id: str,
        src_path: str,
        segments_raw: list,
        segment_paths: list,
        tmp: TempFileManager,
    ) -> None:
        from reframe_service import ffprobe_video
        from promo_service import create_title_card_video

        self.update_status(record_id, "extracting", 52)
        logger.info(f"[promo:{record_id}] Generating thumbnail title card...")

        probe = ffprobe_video(src_path)
        orientation = "16:9" if probe["width"] > probe["height"] else "9:16"

        loop = asyncio.new_event_loop()
        try:
            thumb_result = loop.run_until_complete(
                deps.ai_svc.generate_promo_thumbnail(
                    title=record.source_filename or "PROMO",
                    description=f"Highlight reel with {len(segments_raw)} moments",
                    orientation=orientation,
                )
            )
        finally:
            loop.close()

        thumb_gcs_uri = thumb_result.data["image_url"]
        deps.firestore_svc.update_promo_record(
            record_id, {"thumbnail_gcs_uri": thumb_gcs_uri}
        )

        # Download thumbnail image, create title card video
        thumb_img_path = tmp.create(suffix=".png")
        deps.storage_svc.download_to_file(thumb_gcs_uri, thumb_img_path)

        title_card_path = tmp.create(suffix="_titlecard.mp4")
        create_title_card_video(
            thumb_img_path,
            title_card_path,
            width=probe["width"],
            height=probe["height"],
        )
        segment_paths.insert(0, title_card_path)
        logger.info(f"[promo:{record_id}] Title card created, prepended to segments")

    def _apply_text_overlays(
        self,
        record,
        record_id: str,
        src_path: str,
        segments_raw: list,
        segment_paths: list,
        tmp: TempFileManager,
    ) -> None:
        from reframe_service import ffprobe_video
        from promo_service import overlay_image_on_segment

        self.update_status(record_id, "extracting", 54)
        logger.info(f"[promo:{record_id}] Generating text overlays...")

        probe = ffprobe_video(src_path)
        orientation = "16:9" if probe["width"] > probe["height"] else "9:16"

        # Skip first segment if thumbnail is prepended (it's the title card)
        start_idx = 1 if record.generate_thumbnail else 0

        for i, seg in enumerate(segments_raw):
            # Pause between Gemini image calls to avoid rate limits
            if i > 0:
                time.sleep(5)
            seg_idx = i + start_idx

            loop = asyncio.new_event_loop()
            try:
                overlay_result = loop.run_until_complete(
                    deps.ai_svc.generate_text_overlay(
                        text=seg.get("title", ""),
                        orientation=orientation,
                    )
                )
            finally:
                loop.close()

            # Download overlay image
            ovr_img_path = tmp.create(suffix=f"_ovr{i}.png")
            deps.storage_svc.download_to_file(
                overlay_result.data["image_url"], ovr_img_path
            )

            # Overlay on segment
            overlaid_path = tmp.create(suffix=f"_overlaid{i}.mp4")
            overlay_image_on_segment(
                segment_paths[seg_idx], ovr_img_path, overlaid_path
            )
            segment_paths[seg_idx] = overlaid_path

            logger.info(
                f"[promo:{record_id}] Overlay {i + 1}/{len(segments_raw)}: {seg.get('title', '')}"
            )
