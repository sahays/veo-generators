"""Reframe job processor — analyzes focal points and crops landscape video to portrait."""

import logging
import os
import time

import deps
from cost_tracking import (
    accumulate_diarization_cost,
    accumulate_transcoder_cost,
)
from models import FocalPoint, SpeakerSegment

from base_processor import JobProcessor, TempFileManager
from _reframe_helpers import format_chirp_context, format_track_summary

logger = logging.getLogger(__name__)


class ReframeProcessor(JobProcessor):
    """Processes pending reframe jobs."""

    @property
    def name(self) -> str:
        return "reframe"

    @property
    def firestore_update_method(self) -> str:
        return "update_reframe_record"

    def get_pending_records(self) -> list:
        return deps.firestore_svc.get_reframe_records(include_archived=False)

    def process(self, record) -> None:
        record_id = record.id
        tmp = TempFileManager()
        try:
            src_path, probe = self._download_and_probe(record, record_id, tmp)
            out_path = tmp.create(suffix=".mp4")

            if record.vertical_split:
                self._run_vertical_split(record_id, src_path, out_path, probe)
            else:
                self._run_ai_reframe(record, record_id, src_path, out_path, probe, tmp)

            self.update_status(record_id, "processing", 65)
            output_uri = self._upload_and_encode(record, record_id, out_path, probe)
            self.update_status(record_id, "completed", 100, output_gcs_uri=output_uri)
            logger.info(f"[reframe:{record_id}] Completed: {output_uri}")
        finally:
            tmp.cleanup()

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _download_and_probe(self, record, record_id, tmp):
        """Step 1: Download source video and probe dimensions."""
        from reframe_service import ffprobe_video

        self.update_status(record_id, "processing", 5)
        logger.info(f"[reframe:{record_id}] Downloading source video...")
        src_path = tmp.create(suffix=".mp4")
        deps.storage_svc.download_to_file(record.source_gcs_uri, src_path)
        probe = ffprobe_video(src_path)
        logger.info(
            f"[reframe:{record_id}] Source: {probe['width']}x{probe['height']} "
            f"@ {probe['fps']}fps, {probe['duration']:.1f}s, audio={probe.get('has_audio', True)}"
        )
        if probe["width"] <= probe["height"]:
            raise ValueError(
                f"Source not landscape ({probe['width']}x{probe['height']}). "
                "Reframe requires 16:9 or wider."
            )
        return src_path, probe

    def _run_vertical_split(self, record_id, src_path, out_path, probe):
        """Vertical split path: no AI, just split and stack."""
        from reframe_service import execute_vertical_split

        self.update_status(record_id, "processing", 45)
        logger.info(f"[reframe:{record_id}] Running vertical split...")
        execute_vertical_split(
            src_path=src_path,
            out_path=out_path,
            src_w=probe["width"],
            src_h=probe["height"],
            has_audio=probe.get("has_audio", True),
        )

    def _run_ai_reframe(self, record, record_id, src_path, out_path, probe, tmp):
        """AI reframe: diarize → MediaPipe detect → Gemini scenes → merge → smooth → crop."""
        from reframe_service import execute_reframe
        from reframe_strategies import get_strategy

        content_type = record.content_type or "other"
        strategy = get_strategy(content_type)
        has_audio = probe.get("has_audio", True)

        chirp_context = self._run_diarization(
            record, record_id, src_path, probe, tmp, strategy, has_audio
        )

        self.update_status(record_id, "processing", 15)
        tracked_frames = self._run_mediapipe(record_id, src_path)
        track_summary = format_track_summary(tracked_frames)
        deps.firestore_svc.update_reframe_record(
            record_id, {"track_summary": track_summary}
        )

        scenes = self._analyze_scenes(
            record, record_id, content_type, chirp_context, track_summary
        )
        focal_raw = self._merge_scenes_and_tracks(
            record_id, scenes, tracked_frames, probe["duration"]
        )
        keypoints = self._smooth(record_id, focal_raw, probe, strategy)

        self.update_status(record_id, "processing", 45)
        logger.info(
            f"[reframe:{record_id}] Running FFmpeg crop (blurred_bg={record.blurred_bg})"
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

    def _run_diarization(
        self, record, record_id, src_path, probe, tmp, strategy, has_audio
    ):
        """Step 2: Chirp 3 speaker diarization (if enabled)."""
        chirp_context = ""
        use_diarization = strategy.get("use_diarization", False)
        logger.info(
            f"[reframe:{record_id}] Diarization: enabled={use_diarization}, "
            f"audio={has_audio}, svc={'yes' if deps.diarization_svc else 'NO'}"
        )
        if not (use_diarization and has_audio and deps.diarization_svc):
            return chirp_context

        self.update_status(record_id, "analyzing", 10)
        logger.info(f"[reframe:{record_id}] Running Chirp 3 diarization...")
        try:
            from diarization_service import extract_audio

            audio_path = tmp.create(suffix=".wav")
            extract_audio(src_path, audio_path)

            bucket = os.getenv("GCS_BUCKET")
            audio_uri = f"gs://{bucket}/reframes/{record_id}/audio.wav"
            deps.storage_svc.upload_from_file(audio_path, audio_uri)

            result = deps.diarization_svc.transcribe_with_diarization(
                audio_gcs_uri=audio_uri,
                storage_svc=deps.storage_svc,
                record_id=record_id,
                audio_duration=probe["duration"],
            )
            segments = result.get("speaker_segments", [])
            deps.firestore_svc.update_reframe_record(
                record_id,
                {"speaker_segments": [SpeakerSegment(**s).dict() for s in segments]},
            )
            logger.info(f"[reframe:{record_id}] Chirp 3: {len(segments)} segments")
            chirp_context = format_chirp_context(segments)
            accumulate_diarization_cost("reframe", record_id, probe["duration"] / 60.0)
        except Exception as e:
            raise RuntimeError(f"Chirp 3 diarization failed: {e}") from e
        return chirp_context

    def _analyze_scenes(
        self, record, record_id, content_type, chirp_context, track_summary=""
    ):
        """Step 3b: Gemini scene analysis, informed by MediaPipe tracks."""
        self.update_status(record_id, "analyzing", 20)
        logger.info(
            f"[reframe:{record_id}] Gemini scene analysis (type={content_type})"
        )

        # Combine Chirp + track summary as context for Gemini
        context = "\n\n".join(filter(None, [chirp_context, track_summary]))
        result = self._run_async(
            deps.ai_svc.analyze_video_scenes(
                gcs_uri=record.source_gcs_uri,
                mime_type="video/mp4",
                content_type=content_type,
                chirp_context=context,
                model_id=getattr(record, "model_id", None),
                region=getattr(record, "region", None),
            )
        )
        scenes = result.data.get("scenes", [])
        deps.firestore_svc.update_reframe_record(
            record_id,
            {
                "prompt_variables": result.data.get("prompt_variables", {}),
                "prompt_text_used": result.data.get("prompt_text_used", ""),
                "usage": result.usage.dict(),
                "gemini_scenes": scenes,
            },
        )
        logger.info(f"[reframe:{record_id}] {len(scenes)} scenes from Gemini")
        return scenes

    def _run_mediapipe(self, record_id, src_path):
        """Step 3b: MediaPipe face/pose detection + tracking."""
        from mediapipe_detection import scan_video_faces, track_faces

        logger.info(f"[reframe:{record_id}] MediaPipe scanning at 0.5fps...")
        frames_data = scan_video_faces(src_path, sample_fps=0.5)
        tracked = track_faces(frames_data)
        logger.info(f"[reframe:{record_id}] MediaPipe: {len(tracked)} tracked frames")
        return tracked

    def _merge_scenes_and_tracks(self, record_id, scenes, tracked_frames, duration):
        """Step 4: Merge Gemini scenes with MediaPipe tracks → focal points."""
        from mediapipe_detection import merge_scenes_with_tracks

        focal_raw = merge_scenes_with_tracks(scenes, tracked_frames, duration)
        # Store focal points on record for display
        deps.firestore_svc.update_reframe_record(
            record_id,
            {
                "focal_points": [FocalPoint(**fp).dict() for fp in focal_raw],
            },
        )
        logger.info(f"[reframe:{record_id}] Merged: {len(focal_raw)} focal points")
        return focal_raw

    def _smooth(self, record_id, focal_raw, probe, strategy):
        """Step 5: Path smoothing with velocity limits."""
        from reframe_service import smooth_focal_path

        self.update_status(record_id, "processing", 35)
        keypoints = smooth_focal_path(
            focal_points=focal_raw,
            scene_changes=[],
            duration=probe["duration"],
            fps=probe["fps"],
            max_velocity=strategy["max_velocity"],
            deadzone=strategy["deadzone"],
        )
        logger.info(f"[reframe:{record_id}] {len(keypoints)} keypoints after smoothing")
        return keypoints

    def _upload_and_encode(self, record, record_id, out_path, probe):
        """Step 5-6: Upload to GCS and transcode."""
        has_audio = probe.get("has_audio", True)
        logger.info(f"[reframe:{record_id}] Uploading cropped video...")
        bucket = os.getenv("GCS_BUCKET")
        intermediate_uri = f"gs://{bucket}/reframes/{record_id}/cropped.mp4"
        deps.storage_svc.upload_from_file(out_path, intermediate_uri)

        self.update_status(record_id, "encoding", 75)
        if not deps.transcoder_svc:
            return intermediate_uri

        logger.info(f"[reframe:{record_id}] Starting Transcoder encode...")
        job_name, output_uri = deps.transcoder_svc.reframe_encode(
            record_id,
            intermediate_uri,
            has_audio=has_audio,
            blurred_bg=record.blurred_bg,
        )
        self._poll_transcoder(record_id, job_name)
        accumulate_transcoder_cost("reframe", record_id, probe["duration"] / 60.0)
        return output_uri

    def _poll_transcoder(self, record_id, job_name):
        """Poll transcoder job until complete or timeout."""
        elapsed, timeout = 0, 600
        while elapsed < timeout:
            status = deps.transcoder_svc.get_job_status(job_name)
            logger.info(f"[reframe:{record_id}] Transcoder: {status} ({elapsed}s)")
            if status == "SUCCEEDED":
                return
            if status in ("FAILED", "UNKNOWN"):
                raise RuntimeError(f"Transcoder job failed: {status}")
            time.sleep(10)
            elapsed += 10
            self.update_status(
                record_id, "encoding", min(90, 75 + int(elapsed / timeout * 15))
            )
        raise RuntimeError("Transcoder job timed out")
