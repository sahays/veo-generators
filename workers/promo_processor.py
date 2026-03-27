"""
Promo job processor — selects highlight moments and stitches them into a promo video.
"""

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

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
            normalize_segment,
            concatenate_with_crossfade,
        )

        record_id = record.id
        tmp = TempFileManager()

        try:
            # --- Step 1: Gemini selects moments (skip if segments exist) ---
            if record.segments:
                segments_raw = [s.dict() for s in record.segments]
                logger.info(
                    f"[promo:{record_id}] Resuming — reusing {len(segments_raw)} existing segments"
                )
            else:
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
                # Use the saved version so overlay_gcs_uri keys are present
                segments_raw = segments
                logger.info(f"[promo:{record_id}] Got {len(segments_raw)} segments")

            # --- Step 2: Download source video ---
            self.update_status(record_id, "extracting", 20)
            logger.info(f"[promo:{record_id}] Downloading source video...")

            src_path = tmp.create(suffix=".mp4")
            deps.storage_svc.download_to_file(record.source_gcs_uri, src_path)
            logger.info(f"[promo:{record_id}] Downloaded to {src_path}")

            # --- Step 3: Extract each segment (parallel) ---
            extract_tasks = []
            for i, seg in enumerate(segments_raw):
                start_sec = parse_timestamp(seg["timestamp_start"])
                end_sec = parse_timestamp(seg["timestamp_end"])
                seg_path = tmp.create(suffix=f"_seg{i}.mp4")
                extract_tasks.append((i, seg, seg_path, start_sec, end_sec))

            segment_paths = []
            valid_segments_raw = []
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(extract_segment, src_path, t[2], t[3], t[4]): t
                    for t in extract_tasks
                }
                for future in futures:
                    i, seg, seg_path, _, _ = futures[future]
                    try:
                        future.result()
                        segment_paths.append((i, seg, seg_path))
                    except RuntimeError as e:
                        logger.warning(
                            f"[promo:{record_id}] Skipping segment {i} "
                            f"({seg['timestamp_start']}-{seg['timestamp_end']}): {e}"
                        )

            # Sort by original index to preserve order
            segment_paths.sort(key=lambda x: x[0])
            valid_segments_raw = [s[1] for s in segment_paths]
            segment_paths = [s[2] for s in segment_paths]
            segments_raw = valid_segments_raw
            self.update_status(record_id, "extracting", 50)
            logger.info(f"[promo:{record_id}] Extracted {len(segment_paths)} segments")

            if not segment_paths:
                raise ValueError("No valid segments could be extracted")

            # --- Step 3b: Generate thumbnail title card ---
            if record.generate_thumbnail:
                try:
                    self._generate_title_card(
                        record, record_id, src_path, segments_raw, segment_paths, tmp
                    )
                except Exception as e:
                    logger.warning(
                        f"[promo:{record_id}] Title card failed, skipping: {e}"
                    )

            # --- Step 3c: Generate text overlays ---
            if record.text_overlay:
                self._apply_text_overlays(
                    record, record_id, src_path, segments_raw, segment_paths, tmp
                )

            # --- Step 3d: Normalize all segments to canonical format ---
            self.update_status(record_id, "stitching", 55)
            logger.info(f"[promo:{record_id}] Normalizing segments...")

            from reframe_service import ffprobe_video

            probe = ffprobe_video(src_path)
            target_w = probe["width"] // 2 * 2
            target_h = probe["height"] // 2 * 2

            norm_tasks = [
                (i, seg_path, tmp.create(suffix=f"_norm{i}.mp4"))
                for i, seg_path in enumerate(segment_paths)
            ]
            normalized_paths = []
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(normalize_segment, t[1], t[2], target_w, target_h): t
                    for t in norm_tasks
                }
                for future in futures:
                    i, _, norm_path = futures[future]
                    try:
                        future.result()
                        normalized_paths.append((i, norm_path))
                    except RuntimeError as e:
                        logger.warning(
                            f"[promo:{record_id}] Skipping segment {i} — normalization failed: {e}"
                        )
            normalized_paths.sort(key=lambda x: x[0])
            segment_paths = [p[1] for p in normalized_paths]

            logger.info(
                f"[promo:{record_id}] Normalized {len(segment_paths)} segments "
                f"to {target_w}x{target_h}@30fps"
            )

            # --- Step 4: Concatenate with cross-dissolve ---
            self.update_status(record_id, "stitching", 60)
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
        from promo_service import (
            create_title_card_video,
            extract_frame,
            parse_timestamp,
        )

        self.update_status(record_id, "extracting", 52)

        probe = ffprobe_video(src_path)
        orientation = "16:9" if probe["width"] > probe["height"] else "9:16"

        # Reuse existing thumbnail if available (checkpoint)
        if record.thumbnail_gcs_uri:
            logger.info(f"[promo:{record_id}] Resuming — reusing existing thumbnail")
            thumb_gcs_uri = record.thumbnail_gcs_uri
        else:
            logger.info(f"[promo:{record_id}] Generating collage title card...")

            # Extract frames from first 3-4 key moments
            frame_uris = []
            max_frames = min(4, len(segments_raw))
            bucket = os.getenv("GCS_BUCKET")
            for i in range(max_frames):
                seg = segments_raw[i]
                start = parse_timestamp(seg["timestamp_start"])
                end = parse_timestamp(seg["timestamp_end"])
                midpoint = (start + end) / 2

                frame_path = tmp.create(suffix=f"_frame{i}.png")
                extract_frame(src_path, frame_path, midpoint)

                # Upload frame to GCS
                import uuid as _uuid

                dest = f"promos/frames/{_uuid.uuid4()}.png"
                frame_uri = deps.storage_svc.upload_from_file(
                    frame_path, f"gs://{bucket}/{dest}", content_type="image/png"
                )
                frame_uris.append(frame_uri)
                logger.info(f"[promo:{record_id}] Extracted frame {i + 1}/{max_frames}")

            # Generate collage from frames
            loop = asyncio.new_event_loop()
            try:
                collage_result = loop.run_until_complete(
                    deps.ai_svc.generate_promo_collage(
                        screenshot_uris=frame_uris,
                        segments=segments_raw,
                        orientation=orientation,
                    )
                )
            finally:
                loop.close()

            thumb_gcs_uri = collage_result.data["image_url"]
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

        # Phase 1: Collect all overlay images (Gemini calls — sequential)
        overlay_images: list[tuple[int, str]] = []  # (seg_idx, ovr_img_path)
        for i, seg in enumerate(segments_raw):
            seg_idx = i + start_idx
            existing_uri = seg.get("overlay_gcs_uri")

            if existing_uri:
                logger.info(f"[promo:{record_id}] Resuming — reusing overlay {i}")
                ovr_img_path = tmp.create(suffix=f"_ovr{i}.png")
                deps.storage_svc.download_to_file(existing_uri, ovr_img_path)
            else:
                if i > 0:
                    time.sleep(5)

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

                overlay_uri = overlay_result.data["image_url"]
                segments_raw[i]["overlay_gcs_uri"] = overlay_uri
                deps.firestore_svc.update_promo_record(
                    record_id, {"segments": segments_raw}
                )

                ovr_img_path = tmp.create(suffix=f"_ovr{i}.png")
                deps.storage_svc.download_to_file(overlay_uri, ovr_img_path)

            overlay_images.append((seg_idx, ovr_img_path))
            logger.info(
                f"[promo:{record_id}] Overlay image {i + 1}/{len(segments_raw)}: {seg.get('title', '')}"
            )

        # Phase 2: Apply overlays to segments (FFmpeg — parallel)
        def _apply_one_overlay(seg_idx: int, ovr_path: str) -> tuple[int, str]:
            out = tmp.create(suffix=f"_overlaid{seg_idx}.mp4")
            overlay_image_on_segment(segment_paths[seg_idx], ovr_path, out)
            return seg_idx, out

        logger.info(
            f"[promo:{record_id}] Compositing {len(overlay_images)} overlays in parallel..."
        )
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(_apply_one_overlay, seg_idx, ovr_path)
                for seg_idx, ovr_path in overlay_images
            ]
            for future in futures:
                seg_idx, overlaid_path = future.result()
                segment_paths[seg_idx] = overlaid_path
