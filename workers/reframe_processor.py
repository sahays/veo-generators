"""
Reframe job processor — analyzes focal points and crops landscape video to portrait.
"""

import asyncio
import logging
import os
import time

import deps
from models import FocalPoint, SceneChange

from base_processor import JobProcessor, TempFileManager

logger = logging.getLogger(__name__)


class ReframeProcessor(JobProcessor):
    """Processes pending reframe jobs."""

    @property
    def name(self) -> str:
        return "reframe"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_reframe_records(include_archived=False)

    def update_status(
        self, record_id: str, status: str, progress: int, **extra
    ) -> None:
        updates = {"status": status, "progress_pct": progress, **extra}
        self._set_completion_timestamp(updates, status)
        deps.firestore_svc.update_reframe_record(record_id, updates)

    def mark_failed(self, record_id: str, error_message: str) -> None:
        self.update_status(record_id, "failed", 0, error_message=error_message)

    def process(self, record) -> None:
        from reframe_service import ffprobe_video, smooth_focal_path, execute_reframe

        record_id = record.id
        tmp = TempFileManager()

        try:
            # --- Step 1: Gemini focal point analysis ---
            self.update_status(record_id, "analyzing", 5)
            logger.info(f"[reframe:{record_id}] Analyzing focal points...")

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    deps.ai_svc.analyze_video_focal_points(
                        gcs_uri=record.source_gcs_uri,
                        mime_type="video/mp4",
                        prompt_id=record.prompt_id,
                    )
                )
            finally:
                loop.close()

            focal_points_raw = result.data.get("focal_points", [])
            scene_changes_raw = result.data.get("scene_changes", [])

            deps.firestore_svc.update_reframe_record(
                record_id,
                {
                    "focal_points": [
                        FocalPoint(**fp).dict() for fp in focal_points_raw
                    ],
                    "scene_changes": [
                        SceneChange(**sc).dict() for sc in scene_changes_raw
                    ],
                    "usage": result.usage.dict(),
                },
            )
            logger.info(
                f"[reframe:{record_id}] Got {len(focal_points_raw)} focal points, "
                f"{len(scene_changes_raw)} scene changes"
            )

            # --- Step 2: Download, probe, compute path, FFmpeg ---
            self.update_status(record_id, "processing", 20)
            logger.info(f"[reframe:{record_id}] Downloading source video...")

            src_path = tmp.create(suffix=".mp4")
            deps.storage_svc.download_to_file(record.source_gcs_uri, src_path)
            file_size = os.path.getsize(src_path)
            logger.info(
                f"[reframe:{record_id}] Downloaded to {src_path} ({file_size} bytes)"
            )

            probe = ffprobe_video(src_path)
            has_audio = probe.get("has_audio", True)
            logger.info(
                f"[reframe:{record_id}] Source: {probe['width']}x{probe['height']} "
                f"@ {probe['fps']}fps, {probe['duration']:.1f}s, audio={has_audio}"
            )

            if probe["width"] <= probe["height"]:
                raise ValueError(
                    f"Source video is not landscape ({probe['width']}x{probe['height']}). "
                    "Reframe requires a 16:9 or wider landscape video."
                )

            self.update_status(record_id, "processing", 30)

            # OpenCV validation: correct Gemini's focal points with actual detection
            from cv_validation import validate_focal_points

            logger.info(f"[reframe:{record_id}] Running OpenCV validation...")
            focal_points_raw = validate_focal_points(
                video_path=src_path,
                focal_points=focal_points_raw,
                video_w=probe["width"],
                video_h=probe["height"],
                sports_mode=record.sports_mode,
            )

            self.update_status(record_id, "processing", 35)

            # Sports mode: higher velocity, smaller deadzone
            if record.sports_mode:
                max_vel, dz = 0.50, 0.02
                logger.info(f"[reframe:{record_id}] Sports mode enabled")
            else:
                max_vel, dz = 0.15, 0.05

            keypoints = smooth_focal_path(
                focal_points=focal_points_raw,
                scene_changes=scene_changes_raw,
                duration=probe["duration"],
                fps=probe["fps"],
                max_velocity=max_vel,
                deadzone=dz,
            )
            logger.info(
                f"[reframe:{record_id}] {len(keypoints)} keypoints "
                f"(first: {keypoints[0] if keypoints else 'none'}, "
                f"last: {keypoints[-1] if keypoints else 'none'})"
            )

            out_path = tmp.create(suffix=".mp4")

            self.update_status(record_id, "processing", 45)
            logger.info(
                f"[reframe:{record_id}] Running FFmpeg crop... "
                f"(blurred_bg={record.blurred_bg})"
            )

            execute_reframe(
                src_path=src_path,
                out_path=out_path,
                keypoints=keypoints,
                src_w=probe["width"],
                src_h=probe["height"],
                has_audio=has_audio,
                blurred_bg=record.blurred_bg,
            )

            self.update_status(record_id, "processing", 65)

            # --- Step 3: Upload cropped video to GCS ---
            logger.info(f"[reframe:{record_id}] Uploading cropped video...")
            bucket = os.getenv("GCS_BUCKET")
            intermediate_uri = f"gs://{bucket}/reframes/{record_id}/cropped.mp4"
            deps.storage_svc.upload_from_file(out_path, intermediate_uri)

            # --- Step 4: Transcoder encode ---
            self.update_status(record_id, "encoding", 75)
            logger.info(f"[reframe:{record_id}] Starting Transcoder encode...")

            if deps.transcoder_svc:
                job_name, output_uri = deps.transcoder_svc.reframe_encode(
                    record_id, intermediate_uri, has_audio=has_audio
                )
                logger.info(f"[reframe:{record_id}] Transcoder job: {job_name}")

                elapsed = 0
                timeout = 600
                while elapsed < timeout:
                    status = deps.transcoder_svc.get_job_status(job_name)
                    logger.info(
                        f"[reframe:{record_id}] Transcoder: {status} ({elapsed}s)"
                    )
                    if status == "SUCCEEDED":
                        break
                    if status in ("FAILED", "UNKNOWN"):
                        raise RuntimeError(
                            f"Transcoder job failed with status: {status}"
                        )
                    time.sleep(10)
                    elapsed += 10
                    progress = min(90, 75 + int(elapsed / timeout * 15))
                    self.update_status(record_id, "encoding", progress)

                if elapsed >= timeout:
                    raise RuntimeError("Transcoder job timed out")
            else:
                output_uri = intermediate_uri

            # --- Step 5: Done ---
            self.update_status(record_id, "completed", 100, output_gcs_uri=output_uri)
            logger.info(f"[reframe:{record_id}] Completed: {output_uri}")

        finally:
            tmp.cleanup()
