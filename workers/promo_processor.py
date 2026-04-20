"""Promo job processor — selects highlight moments and stitches them into a promo video."""

import asyncio
import logging
import os
import time
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor

import deps
from cost_tracking import accumulate_image_cost_on
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
        record_id = record.id
        tmp = TempFileManager()
        try:
            segments_raw = self._analyze_or_resume(record, record_id)
            src_path = self._download_source(record, record_id, tmp)
            segment_paths, segments_raw = self._extract_segments(
                record_id,
                src_path,
                segments_raw,
                tmp,
            )
            self._optional_title_card(
                record, record_id, src_path, segments_raw, segment_paths, tmp
            )
            self._optional_text_overlays(
                record, record_id, src_path, segments_raw, segment_paths, tmp
            )
            output_uri = self._normalize_and_stitch(
                record, record_id, src_path, segment_paths, tmp
            )
            self.update_status(record_id, "completed", 100, output_gcs_uri=output_uri)
            logger.info(f"[promo:{record_id}] Completed: {output_uri}")
        finally:
            tmp.cleanup()

    # ------------------------------------------------------------------
    # Step 1: Gemini analysis (or resume from checkpoint)
    # ------------------------------------------------------------------

    def _analyze_or_resume(self, record, record_id) -> list:
        """Get segments from checkpoint or run Gemini analysis."""
        if record.segments:
            segments_raw = [s.dict() for s in record.segments]
            logger.info(
                f"[promo:{record_id}] Resuming with {len(segments_raw)} segments"
            )
            return segments_raw

        self.update_status(record_id, "analyzing", 5)
        logger.info(f"[promo:{record_id}] Analyzing video for promo...")
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
        logger.info(f"[promo:{record_id}] Got {len(segments)} segments")
        return segments

    # ------------------------------------------------------------------
    # Step 2: Download source
    # ------------------------------------------------------------------

    def _download_source(self, record, record_id, tmp) -> str:
        self.update_status(record_id, "extracting", 20)
        logger.info(f"[promo:{record_id}] Downloading source video...")
        src_path = tmp.create(suffix=".mp4")
        deps.storage_svc.download_to_file(record.source_gcs_uri, src_path)
        return src_path

    # ------------------------------------------------------------------
    # Step 3: Extract segments (parallel)
    # ------------------------------------------------------------------

    def _extract_segments(self, record_id, src_path, segments_raw, tmp):
        """Extract each segment in parallel, skip failures."""
        from promo_service import parse_timestamp, extract_segment

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

        results = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(
                    extract_segment, src_path, t["path"], t["start"], t["end"]
                ): t
                for t in tasks
            }
            for future in futures:
                t = futures[future]
                try:
                    future.result()
                    results.append(t)
                except RuntimeError as e:
                    logger.warning(
                        f"[promo:{record_id}] Skipping segment {t['idx']}: {e}"
                    )

        results.sort(key=lambda t: t["idx"])
        self.update_status(record_id, "extracting", 50)
        logger.info(f"[promo:{record_id}] Extracted {len(results)} segments")
        if not results:
            raise ValueError("No valid segments could be extracted")
        return [t["path"] for t in results], [t["seg"] for t in results]

    # ------------------------------------------------------------------
    # Step 3b: Optional title card
    # ------------------------------------------------------------------

    def _optional_title_card(
        self, record, record_id, src_path, segments_raw, segment_paths, tmp
    ):
        if not record.generate_thumbnail:
            return
        try:
            self._generate_title_card(
                record, record_id, src_path, segments_raw, segment_paths, tmp
            )
        except Exception as e:
            logger.warning(f"[promo:{record_id}] Title card failed, skipping: {e}")

    def _generate_title_card(
        self, record, record_id, src_path, segments_raw, segment_paths, tmp
    ):
        from ffmpeg_runner import ffprobe_video
        from promo_service import create_title_card_video

        self.update_status(record_id, "extracting", 52)
        probe = ffprobe_video(src_path)
        orientation = "16:9" if probe["width"] > probe["height"] else "9:16"

        thumb_uri = self._get_or_create_thumbnail(
            record,
            record_id,
            src_path,
            segments_raw,
            orientation,
            probe,
            tmp,
        )
        thumb_img = tmp.create(suffix=".png")
        deps.storage_svc.download_to_file(thumb_uri, thumb_img)
        title_card = tmp.create(suffix="_titlecard.mp4")
        create_title_card_video(
            thumb_img, title_card, width=probe["width"], height=probe["height"]
        )
        segment_paths.insert(0, title_card)
        logger.info(f"[promo:{record_id}] Title card prepended")

    def _get_or_create_thumbnail(
        self, record, record_id, src_path, segments_raw, orientation, probe, tmp
    ):
        """Return existing thumbnail URI or generate a new collage."""
        if record.thumbnail_gcs_uri:
            logger.info(f"[promo:{record_id}] Reusing existing thumbnail")
            return record.thumbnail_gcs_uri

        frame_uris = self._extract_key_frames(record_id, src_path, segments_raw, tmp)
        result = self._run_async(
            deps.ai_svc.generate_promo_collage(
                screenshot_uris=frame_uris,
                segments=segments_raw,
                orientation=orientation,
            )
        )
        uri = result.data["image_url"]
        accumulate_image_cost_on(
            "promo",
            record_id,
            result.usage.cost_usd,
            input_tokens=result.usage.image_input_tokens,
            output_tokens=result.usage.image_output_tokens,
        )
        deps.firestore_svc.update_promo_record(record_id, {"thumbnail_gcs_uri": uri})
        return uri

    def _extract_key_frames(self, record_id, src_path, segments_raw, tmp) -> list:
        """Extract frames from first few key moments and upload to GCS."""
        from promo_service import extract_frame, parse_timestamp

        bucket = os.getenv("GCS_BUCKET")
        key_segments = segments_raw[:4]
        uris = []
        for i, seg in enumerate(key_segments):
            mid = (
                parse_timestamp(seg["timestamp_start"])
                + parse_timestamp(seg["timestamp_end"])
            ) / 2
            frame_path = tmp.create(suffix=f"_frame{i}.png")
            extract_frame(src_path, frame_path, mid)
            gcs_path = f"gs://{bucket}/promos/frames/{_uuid.uuid4()}.png"
            uris.append(
                deps.storage_svc.upload_from_file(
                    frame_path, gcs_path, content_type="image/png"
                )
            )
            logger.info(f"[promo:{record_id}] Frame {i + 1}/{len(key_segments)}")
        return uris

    # ------------------------------------------------------------------
    # Step 3c: Optional text overlays
    # ------------------------------------------------------------------

    def _optional_text_overlays(
        self, record, record_id, src_path, segments_raw, segment_paths, tmp
    ):
        if not record.text_overlay:
            return
        self._apply_text_overlays(
            record, record_id, src_path, segments_raw, segment_paths, tmp
        )

    def _apply_text_overlays(
        self, record, record_id, src_path, segments_raw, segment_paths, tmp
    ):
        from ffmpeg_runner import ffprobe_video

        self.update_status(record_id, "extracting", 54)
        probe = ffprobe_video(src_path)
        orientation = "16:9" if probe["width"] > probe["height"] else "9:16"
        start_idx = 1 if record.generate_thumbnail else 0

        overlays = self._collect_overlay_images(
            record_id,
            segments_raw,
            orientation,
            start_idx,
            tmp,
        )
        self._composite_overlays(record_id, overlays, segment_paths, tmp)

    def _collect_overlay_images(
        self, record_id, segments_raw, orientation, start_idx, tmp
    ) -> list:
        """Resolve overlay URIs (cached or generated), download each to local path."""
        overlays = []
        for i, seg in enumerate(segments_raw):
            uri = seg.get("overlay_gcs_uri") or self._generate_overlay(
                record_id, segments_raw, i, orientation
            )
            path = tmp.create(suffix=f"_ovr{i}.png")
            deps.storage_svc.download_to_file(uri, path)
            overlays.append((i + start_idx, path))
            logger.info(
                f"[promo:{record_id}] Overlay {i + 1}/{len(segments_raw)}: {seg.get('title', '')}"
            )
        return overlays

    def _generate_overlay(self, record_id, segments_raw, i, orientation) -> str:
        """Generate a text overlay image via Gemini, persist URI, return it."""
        if i > 0:
            time.sleep(5)
        result = self._run_async(
            deps.ai_svc.generate_text_overlay(
                text=segments_raw[i].get("title", ""), orientation=orientation
            )
        )
        uri = result.data["image_url"]
        accumulate_image_cost_on(
            "promo",
            record_id,
            result.usage.cost_usd,
            input_tokens=result.usage.image_input_tokens,
            output_tokens=result.usage.image_output_tokens,
        )
        segments_raw[i]["overlay_gcs_uri"] = uri
        deps.firestore_svc.update_promo_record(record_id, {"segments": segments_raw})
        return uri

    def _composite_overlays(self, record_id, overlays, segment_paths, tmp):
        """Apply overlay images to segments in parallel."""
        from promo_service import overlay_image_on_segment

        logger.info(f"[promo:{record_id}] Compositing {len(overlays)} overlays...")
        with ThreadPoolExecutor(max_workers=4) as pool:

            def apply(seg_idx, ovr_path):
                out = tmp.create(suffix=f"_overlaid{seg_idx}.mp4")
                overlay_image_on_segment(segment_paths[seg_idx], ovr_path, out)
                return seg_idx, out

            futures = [pool.submit(apply, idx, path) for idx, path in overlays]
            for f in futures:
                idx, out = f.result()
                segment_paths[idx] = out

    # ------------------------------------------------------------------
    # Step 3d-5: Normalize, stitch, upload
    # ------------------------------------------------------------------

    def _normalize_and_stitch(
        self, record, record_id, src_path, segment_paths, tmp
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

    def _normalize_parallel(self, record_id, segment_paths, tw, th, tmp) -> list:
        """Normalize all segments to canonical format in parallel."""
        from promo_service import normalize_segment

        tasks = [
            {"idx": i, "src": p, "dest": tmp.create(suffix=f"_norm{i}.mp4")}
            for i, p in enumerate(segment_paths)
        ]
        results = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(normalize_segment, t["src"], t["dest"], tw, th): t
                for t in tasks
            }
            for f in futures:
                t = futures[f]
                try:
                    f.result()
                    results.append(t)
                except RuntimeError as e:
                    logger.warning(
                        f"[promo:{record_id}] Norm failed for segment {t['idx']}: {e}"
                    )
        results.sort(key=lambda t: t["idx"])
        logger.info(
            f"[promo:{record_id}] Normalized {len(results)} segments to {tw}x{th}"
        )
        return [t["dest"] for t in results]

    # ------------------------------------------------------------------
    # Async helper
    # ------------------------------------------------------------------

    def _run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
