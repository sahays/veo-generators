"""Reframe job processor — analyzes focal points and crops landscape video to portrait."""

import logging
import os
import time
from typing import Any, Optional

import deps
from cost_tracking import (
    accumulate_diarization_cost,
    accumulate_text_cost_on,
    accumulate_transcoder_cost,
)

from _reframe_ai_pipeline import (
    analyze_scenes,
    apply_gemini_decisions,
    collect_semantics,
    run_diarization,
)
from _reframe_reporting import (
    dump_detection_fixture,
    store_eval_report,
    store_render_check,
    store_segment_plan,
)
from _reframe_v2_pipeline import (  # noqa: F401
    _mark_outlier_full_frame_shots,
    _resolve_canvas_and_rungs,
    detect_and_scan_video,
    launch_semantic_pass,
    plan_and_evaluate_segments,
    run_ai_reframe_pipeline,
    run_diagnostic_pipeline,
)
from base_processor import JobProcessor, TempFileManager

logger = logging.getLogger(__name__)

__all__ = ["ReframeProcessor", "accumulate_diarization_cost", "accumulate_text_cost_on"]


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

    def process(self, record: Any) -> None:
        record_id = record.id
        tmp = TempFileManager()
        try:
            src_path, probe = self._download_and_probe(record, record_id, tmp)
            out_path = tmp.create(suffix=".mp4")
            if getattr(record, "diagnostic_mode", False):
                self._run_diagnostic(record, record_id, src_path, out_path, probe, tmp)
                output_uri = self._upload_diagnostic(record_id, out_path)
                self.update_status(
                    record_id, "completed", 100, output_gcs_uri=output_uri
                )
                logger.info(
                    f"[reframe:{record_id}] Diagnostic done: {output_uri}",
                    extra={
                        "who": "reframe",
                        "where": "process",
                        "what": f"diagnostic_done:{output_uri}",
                        "why": "diagnostic_mode",
                        "how": "update_status",
                    },
                )
                return

            self._run_ai_reframe(record, record_id, src_path, out_path, probe, tmp)
            self.update_status(record_id, "processing", 65)
            output_uri = self._upload_and_encode(record, record_id, out_path, probe)
            self.update_status(record_id, "completed", 100, output_gcs_uri=output_uri)
            logger.info(
                f"[reframe:{record_id}] Completed: {output_uri}",
                extra={
                    "who": "reframe",
                    "where": "process",
                    "what": f"completed:{output_uri}",
                    "why": "job_done",
                    "how": "update_status",
                },
            )
        finally:
            tmp.cleanup()

    def _run_diagnostic(
        self,
        record: Any,
        record_id: str,
        src_path: str,
        out_path: str,
        probe: dict,
        tmp: TempFileManager,
    ) -> None:
        """Diagnostic mode: run detection, render detector overlays (no crop)."""
        run_diagnostic_pipeline(self, record, record_id, src_path, out_path, probe, tmp)

    def _upload_diagnostic(self, record_id: str, out_path: str) -> str:
        """Upload the diagnostic video (already the output canvas size — no transcode)."""
        bucket = os.getenv("GCS_BUCKET")
        uri = f"gs://{bucket}/reframes/{record_id}/diagnostic.mp4"
        deps.storage_svc.upload_from_file(out_path, uri)
        return uri

    def _download_and_probe(
        self, record: Any, record_id: str, tmp: TempFileManager
    ) -> tuple[str, dict]:
        """Step 1: Download source video and probe dimensions."""
        from reframe_service import ffprobe_video

        self.update_status(record_id, "processing", 5)
        logger.info(
            f"[reframe:{record_id}] Downloading source video...",
            extra={
                "who": "reframe",
                "where": "_download_and_probe",
                "what": record.source_gcs_uri,
                "why": "acquire_source",
                "how": "download_to_file",
            },
        )
        src_path = tmp.create(suffix=".mp4")
        deps.storage_svc.download_to_file(record.source_gcs_uri, src_path)
        probe = ffprobe_video(src_path)
        logger.info(
            f"[reframe:{record_id}] Source: {probe['width']}x{probe['height']} @ {probe['fps']}fps, {probe['duration']:.1f}s, audio={probe.get('has_audio', True)}",
            extra={
                "who": "reframe",
                "where": "_download_and_probe",
                "what": f"{probe['width']}x{probe['height']}",
                "why": "probe_complete",
                "how": "ffprobe_video",
            },
        )
        if probe["width"] < probe["height"]:
            raise ValueError(
                f"Source not landscape ({probe['width']}x{probe['height']}). Reframe requires a landscape or square source."
            )
        return src_path, probe

    def _launch_semantic_pass(
        self, record: Any, cuts: list, chirp_context: str, dur: float
    ) -> tuple[Any, Any]:
        """Start async whole-video semantic pass in background if enabled."""
        return launch_semantic_pass(self, record, cuts, chirp_context, dur)

    def _detect_and_scan(
        self,
        record: Any,
        record_id: str,
        src_path: str,
        probe: dict,
        ar: str,
        tmp: TempFileManager,
    ) -> dict[str, Any]:
        """Run diarization, cut detection, active-area detection, MediaPipe scan, and semantic pass."""
        return detect_and_scan_video(self, record, record_id, src_path, probe, ar, tmp)

    def _plan_and_evaluate(
        self,
        record: Any,
        record_id: str,
        scan: dict[str, Any],
        probe: dict,
        out_h: int,
        rungs: Any,
    ) -> tuple[list[dict], Optional[dict]]:
        """Reconcile segment plan, apply Pass-2 Gemini verdicts, and store evaluation report."""
        return plan_and_evaluate_segments(
            self, record, record_id, scan, probe, out_h, rungs
        )

    def _run_ai_reframe(
        self,
        record: Any,
        record_id: str,
        src_path: str,
        out_path: str,
        probe: dict,
        tmp: TempFileManager,
    ) -> None:
        """v2 adaptive letterbox: cuts -> detect -> Gemini -> plan -> smooth -> render."""
        run_ai_reframe_pipeline(self, record, record_id, src_path, out_path, probe, tmp)

    def _collect_semantics(
        self,
        record_id: str,
        future: Any,
        cuts: list,
        text_frames: list,
        duration: float,
    ) -> tuple[list, str]:
        return collect_semantics(
            record_id, future, cuts, text_frames, duration, accumulate_text_cost_on
        )

    def _dump_detection_fixture(
        self,
        record_id: str,
        probe: dict,
        canvas: str,
        cuts: list,
        det_frames: list,
        text_frames: list,
        speaker_segments: list,
        sample_fps: float,
        active_area: Any = None,
    ) -> None:
        dump_detection_fixture(
            record_id,
            probe,
            canvas,
            cuts,
            det_frames,
            text_frames,
            speaker_segments,
            sample_fps,
            active_area=active_area,
        )

    def _store_segment_plan(
        self,
        record_id: str,
        segments: list[dict],
        semantic_status: str = "off",
        active_area: Any = None,
    ) -> None:
        store_segment_plan(
            record_id,
            segments,
            semantic_status=semantic_status,
            active_area=active_area,
        )

    def _apply_gemini_decisions(
        self,
        record: Any,
        record_id: str,
        segments: list[dict],
        src_path: str,
        src_w: int,
        src_h: int,
        rungs: Any,
        tracked_frames: Optional[list] = None,
        person_frames: Optional[list] = None,
        active_area: Any = None,
    ) -> None:
        apply_gemini_decisions(
            record,
            record_id,
            segments,
            src_path,
            src_w,
            src_h,
            rungs,
            self._run_async,
            accumulate_text_cost_on,
            tracked_frames=tracked_frames,
            person_frames=person_frames,
            active_area=active_area,
        )

    def _store_eval_report(
        self,
        record_id: str,
        segments: list[dict],
        tracked_frames: list,
        person_frames: list,
        speaker_segments: list,
        src_w: int,
        src_h: int,
        duration: float,
        canvas_h: int = 1920,
        rungs: Any = None,
        perception: Optional[dict] = None,
    ) -> Optional[dict]:
        return store_eval_report(
            record_id,
            segments,
            tracked_frames,
            person_frames,
            speaker_segments,
            src_w,
            src_h,
            duration,
            canvas_h=canvas_h,
            rungs=rungs,
            perception=perception,
        )

    def _store_render_check(
        self,
        record_id: str,
        report: Optional[dict],
        out_path: str,
        segments: list[dict],
        src_w: int,
        src_h: int,
        out_w: int,
        out_h: int,
    ) -> None:
        store_render_check(
            record_id, report, out_path, segments, src_w, src_h, out_w, out_h
        )

    def _run_diarization(
        self,
        record: Any,
        record_id: str,
        src_path: str,
        probe: dict,
        tmp: TempFileManager,
        has_audio: bool,
    ) -> tuple[str, list]:
        return run_diarization(
            record_id, src_path, probe, tmp, has_audio, self.update_status
        )

    def _analyze_scenes(
        self,
        record: Any,
        record_id: str,
        chirp_context: str,
        track_summary: str = "",
        cuts: Optional[list] = None,
    ) -> list:
        return analyze_scenes(
            record,
            record_id,
            chirp_context,
            track_summary,
            cuts,
            self._run_async,
            self.update_status,
            accumulate_text_cost_on,
        )

    def _upload_and_encode(
        self, record: Any, record_id: str, out_path: str, probe: dict
    ) -> str:
        """Step 5-6: Upload to GCS and transcode."""
        has_audio = probe.get("has_audio", True)
        ar, _out_w, out_h, _rungs = _resolve_canvas_and_rungs(record)
        logger.info(
            f"[reframe:{record_id}] Uploading cropped video...",
            extra={
                "who": "reframe",
                "where": "_upload_and_encode",
                "what": f"record={record_id}",
                "why": "intermediate_upload",
                "how": "upload_from_file",
            },
        )
        bucket = os.getenv("GCS_BUCKET")
        intermediate_uri = f"gs://{bucket}/reframes/{record_id}/cropped.mp4"
        deps.storage_svc.upload_from_file(out_path, intermediate_uri)

        self.update_status(record_id, "encoding", 75)
        if not deps.transcoder_svc:
            return intermediate_uri

        logger.info(
            f"[reframe:{record_id}] Starting Transcoder encode ({ar})...",
            extra={
                "who": "reframe",
                "where": "_upload_and_encode",
                "what": f"ar={ar},out_h={out_h}",
                "why": "transcode_final",
                "how": "reframe_encode",
            },
        )
        job_name, output_uri = deps.transcoder_svc.reframe_encode(
            record_id,
            intermediate_uri,
            has_audio=has_audio,
            out_h=out_h,
            fps=probe.get("fps") or 0.0,
        )
        self._poll_transcoder(record_id, job_name)
        accumulate_transcoder_cost("reframe", record_id, probe["duration"] / 60.0)
        return output_uri

    def _poll_transcoder(self, record_id: str, job_name: str) -> None:
        """Poll transcoder job until complete or timeout."""
        elapsed, timeout = 0, 600
        while elapsed < timeout:
            status = deps.transcoder_svc.get_job_status(job_name)
            logger.info(
                f"[reframe:{record_id}] Transcoder: {status} ({elapsed}s)",
                extra={
                    "who": "reframe",
                    "where": "_poll_transcoder",
                    "what": f"status={status},elapsed={elapsed}s",
                    "why": "poll_transcoder",
                    "how": "get_job_status",
                },
            )
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
