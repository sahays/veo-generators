"""Reframe job processor — analyzes focal points and crops landscape video to portrait."""

import logging
import os
import time

import deps
from cost_tracking import (
    accumulate_diarization_cost,
    accumulate_text_cost_on,
    accumulate_transcoder_cost,
)
from models import SpeakerSegment

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

            if getattr(record, "diagnostic_mode", False):
                self._run_diagnostic(record, record_id, src_path, out_path, probe, tmp)
                output_uri = self._upload_diagnostic(record_id, out_path)
                self.update_status(
                    record_id, "completed", 100, output_gcs_uri=output_uri
                )
                logger.info(f"[reframe:{record_id}] Diagnostic done: {output_uri}")
                return

            self._run_ai_reframe(record, record_id, src_path, out_path, probe, tmp)

            self.update_status(record_id, "processing", 65)
            output_uri = self._upload_and_encode(record, record_id, out_path, probe)
            self.update_status(record_id, "completed", 100, output_gcs_uri=output_uri)
            logger.info(f"[reframe:{record_id}] Completed: {output_uri}")
        finally:
            tmp.cleanup()

    def _run_diagnostic(self, record, record_id, src_path, out_path, probe, tmp):
        """Diagnostic mode: run detection, render detector overlays (no crop)."""
        from reframe_diagnostic import render_diagnostic

        has_audio = probe.get("has_audio", True)

        chirp_context, _speaker_segments = self._run_diarization(
            record, record_id, src_path, probe, tmp, has_audio
        )

        self.update_status(record_id, "processing", 30)
        # Sample densely (faces + persons) so overlay boxes track subjects closely
        # instead of lingering on stale positions across cuts (this is a viz).
        from mediapipe_detection import scan_video_detections, track_faces

        logger.info(f"[reframe:{record_id}] MediaPipe scanning (faces+persons)...")
        det_frames = scan_video_detections(src_path, sample_fps=4.0)
        tracked_frames = track_faces(
            [{"time_sec": f["time_sec"], "faces": f["faces"]} for f in det_frames]
        )
        person_frames = [
            {"time_sec": f["time_sec"], "persons": f["persons"]} for f in det_frames
        ]
        track_summary = format_track_summary(tracked_frames)
        deps.firestore_svc.update_reframe_record(
            record_id, {"track_summary": track_summary}
        )

        from reframe_plan import attach_keypoints, reconcile
        from scene_detect import detect_cuts
        from text_detect import scan_video_text

        cuts = detect_cuts(src_path)
        text_frames = scan_video_text(src_path)
        scenes = self._analyze_scenes(
            record, record_id, chirp_context, track_summary, cuts=cuts
        )

        # Run the real planner so the diagnostic shows the chosen crop window +
        # the decision trigger per shot (observability), not just detections.
        segments = reconcile(
            scenes,
            tracked_frames,
            cuts,
            probe["width"],
            probe["height"],
            probe["duration"],
            person_frames=person_frames,
            text_frames=text_frames,
        )
        attach_keypoints(segments, probe["fps"])
        self._store_segment_plan(record_id, segments)

        self.update_status(record_id, "processing", 60)
        logger.info(f"[reframe:{record_id}] Rendering diagnostic overlay...")
        render_diagnostic(
            src_path=src_path,
            out_path=out_path,
            tracked_frames=tracked_frames,
            scenes=scenes,
            src_w=probe["width"],
            src_h=probe["height"],
            has_audio=has_audio,
            person_frames=person_frames,
            segments=segments,
        )

    def _upload_diagnostic(self, record_id, out_path):
        """Upload the diagnostic video (already 1080x1920 — no transcode)."""
        bucket = os.getenv("GCS_BUCKET")
        uri = f"gs://{bucket}/reframes/{record_id}/diagnostic.mp4"
        deps.storage_svc.upload_from_file(out_path, uri)
        return uri

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

    def _run_ai_reframe(self, record, record_id, src_path, out_path, probe, tmp):
        """v2 adaptive letterbox: cuts → detect → Gemini → plan → smooth → render."""
        from mediapipe_detection import scan_video_detections, track_faces
        from reframe_filters import OUTPUT_CANVAS
        from reframe_plan import RUNGS_BY_CANVAS, attach_keypoints, reconcile
        from reframe_service import render_plan
        from scene_detect import detect_cuts
        from text_detect import scan_video_text

        has_audio = probe.get("has_audio", True)
        w, h, dur, fps = (
            probe["width"],
            probe["height"],
            probe["duration"],
            probe["fps"],
        )
        # Output canvas + rung ladder per selected aspect ratio (default 9:16).
        ar = getattr(record, "output_aspect_ratio", "9:16") or "9:16"
        out_w, out_h = OUTPUT_CANVAS.get(ar, OUTPUT_CANVAS["9:16"])
        rungs = RUNGS_BY_CANVAS.get(ar, RUNGS_BY_CANVAS["9:16"])
        logger.info(f"[reframe:{record_id}] output {ar} ({out_w}x{out_h})")

        chirp_context, speaker_segments = self._run_diarization(
            record, record_id, src_path, probe, tmp, has_audio
        )

        self.update_status(record_id, "analyzing", 15)
        cuts = detect_cuts(src_path)
        logger.info(f"[reframe:{record_id}] {len(cuts)} cuts detected")

        # Faces + persons in one decode pass; faces drive subject framing, persons
        # cover subjects with no visible face (distant, profile, walking away).
        det_frames = scan_video_detections(src_path, sample_fps=1.0)
        tracked_frames = track_faces(
            [{"time_sec": f["time_sec"], "faces": f["faces"]} for f in det_frames]
        )
        person_frames = [
            {"time_sec": f["time_sec"], "persons": f["persons"]} for f in det_frames
        ]
        track_summary = format_track_summary(tracked_frames)
        deps.firestore_svc.update_reframe_record(
            record_id, {"track_summary": track_summary}
        )

        # Measure on-screen text width (independent pass): refines Gemini's coarse
        # full-width flag so we letterbox to the real text extent, not a blanket
        # 16:9. Best-effort — empty list falls back to Gemini's coverage.
        text_frames = scan_video_text(src_path)

        scenes = self._analyze_scenes(
            record, record_id, chirp_context, track_summary, cuts=cuts
        )

        self.update_status(record_id, "processing", 40)
        segments = reconcile(
            scenes,
            tracked_frames,
            cuts,
            w,
            h,
            dur,
            person_frames=person_frames,
            rungs=rungs,
            text_frames=text_frames,
        )
        attach_keypoints(segments, fps)
        self._store_segment_plan(record_id, segments)
        logger.info(f"[reframe:{record_id}] plan: {len(segments)} segments")

        self._store_eval_report(
            record_id,
            segments,
            tracked_frames,
            person_frames,
            speaker_segments,
            w,
            h,
            dur,
            canvas_h=out_h,
            rungs=rungs,
        )

        self.update_status(record_id, "processing", 50)
        render_plan(
            src_path=src_path,
            out_path=out_path,
            segments=segments,
            src_w=w,
            src_h=h,
            has_audio=has_audio,
            out_w=out_w,
            out_h=out_h,
        )

    def _store_segment_plan(self, record_id, segments):
        """Persist the per-segment decision trace + a run summary (observability)."""
        from collections import Counter

        compact = [
            {
                "start": round(s["start"], 2),
                "end": round(s["end"], 2),
                "layout": s["layout"],
                # split has no inner AR (stacked panels fill the canvas) → null
                "inner_ar": list(s["inner_ar"]) if s["inner_ar"] else None,
                "reason": s.get("reason", ""),
                "trace": s.get("trace"),
            }
            for s in segments
        ]
        ar = Counter(
            "split"
            if s["inner_ar"] is None
            else f"{s['inner_ar'][0]}:{s['inner_ar'][1]}"
            for s in segments
        )
        src = Counter(s.get("trace", {}).get("source") for s in segments)
        # Why did letterboxing (16:9) happen?
        why16 = Counter()
        for s in segments:
            if s["inner_ar"] is None or tuple(s["inner_ar"]) != (16, 9):
                continue
            tr = s.get("trace", {})
            if tr.get("layout") == "keep_both":
                why16["two-face span"] += 1
            elif tr.get("c_text", 0) >= tr.get("c_measured", 0):
                why16["Gemini full-width/coverage"] += 1
            else:
                why16["wide subject"] += 1
        summary = {
            "segments": len(segments),
            "aspect_ratios": dict(ar),
            "sources": dict(src),
            "letterbox_16x9_reasons": dict(why16),
            "hysteresis_segments": sum(
                1 for s in segments if s.get("trace", {}).get("hysteresis")
            ),
            "speaker_segments": src.get("speaker", 0),
            "split_segments": sum(1 for s in segments if s["layout"] == "split"),
        }
        deps.firestore_svc.update_reframe_record(
            record_id, {"segment_plan": compact, "reframe_summary": summary}
        )

    def _store_eval_report(
        self,
        record_id,
        segments,
        tracked_frames,
        person_frames,
        speaker_segments,
        src_w,
        src_h,
        duration,
        canvas_h=1920,
        rungs=None,
    ):
        """Reference-free quality report card (runs before render → visible mid-job).

        Scores the plan against signals that didn't decide it (all detections +
        Chirp speech turns). Never fails the reframe — degrade to no report.
        """
        try:
            from reframe_eval import evaluate

            speech = [
                {"start_sec": s.get("start_sec"), "end_sec": s.get("end_sec")}
                for s in (speaker_segments or [])
            ]
            report = evaluate(
                segments,
                tracked_frames,
                person_frames,
                speech,
                src_w,
                src_h,
                duration,
                canvas_h=canvas_h,
                rungs=rungs,
            )
            if not report:
                return
            deps.firestore_svc.update_reframe_record(record_id, {"eval_report": report})
            lb, talker = report["letterbox"], report.get("talker") or {}
            logger.info(
                f"[reframe:{record_id}] eval: overall={report['overall']} "
                f"face_cut={lb['face_cut_rate']} over_lb={lb['over_letterbox_rate']} "
                f"av_sync={talker.get('av_sync_score')} "
                f"miss={talker.get('speaker_miss_rate')}"
            )
        except Exception as e:
            logger.warning(f"[reframe:{record_id}] eval skipped ({e})")

    def _run_diarization(self, record, record_id, src_path, probe, tmp, has_audio):
        """Step 2: Chirp 3 speaker diarization — runs whenever the source has audio.

        Speaker turns only improve framing (who's talking → which face to follow);
        Gemini ignores them when there's no dialogue, so always run when audio
        is present rather than gating on a manual content type.
        """
        chirp_context = ""
        speaker_segments: list = []
        logger.info(
            f"[reframe:{record_id}] Diarization: audio={has_audio}, "
            f"svc={'yes' if deps.diarization_svc else 'NO'}"
        )
        if not (has_audio and deps.diarization_svc):
            return chirp_context, speaker_segments

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
            speaker_segments = result.get("speaker_segments", [])
            deps.firestore_svc.update_reframe_record(
                record_id,
                {
                    "speaker_segments": [
                        SpeakerSegment(**s).dict() for s in speaker_segments
                    ]
                },
            )
            logger.info(
                f"[reframe:{record_id}] Chirp 3: {len(speaker_segments)} segments"
            )
            chirp_context = format_chirp_context(speaker_segments)
            accumulate_diarization_cost("reframe", record_id, probe["duration"] / 60.0)
        except Exception as e:
            # Diarization only enriches speaker framing — never fail the reframe
            # because it broke. Degrade to no speaker context.
            logger.warning(f"[reframe:{record_id}] Diarization skipped ({e})")
        return chirp_context, speaker_segments

    def _analyze_scenes(
        self,
        record,
        record_id,
        chirp_context,
        track_summary="",
        cuts=None,
    ):
        """Step 3b: Gemini scene analysis, informed by cuts + MediaPipe tracks."""
        self.update_status(record_id, "analyzing", 20)
        logger.info(f"[reframe:{record_id}] Gemini scene analysis")

        # Combine Chirp + track summary as context for Gemini
        context = "\n\n".join(filter(None, [chirp_context, track_summary]))
        result = self._run_async(
            deps.ai_svc.analyze_video_scenes(
                gcs_uri=record.source_gcs_uri,
                mime_type="video/mp4",
                chirp_context=context,
                cuts=cuts,
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
                "gemini_scenes": scenes,
            },
        )
        # Accumulate (don't overwrite) Gemini usage so diarization/transcoder
        # costs recorded before/after this step survive.
        usage = result.usage
        accumulate_text_cost_on(
            "reframe",
            record_id,
            cost_usd=usage.cost_usd,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model_name=usage.model_name,
        )
        logger.info(f"[reframe:{record_id}] {len(scenes)} scenes from Gemini")
        return scenes

    def _run_mediapipe(self, record_id, src_path, sample_fps: float = 0.5):
        """Step 3b: MediaPipe face/pose detection + tracking."""
        from mediapipe_detection import scan_video_faces, track_faces

        logger.info(f"[reframe:{record_id}] MediaPipe scanning at {sample_fps}fps...")
        frames_data = scan_video_faces(src_path, sample_fps=sample_fps)
        tracked = track_faces(frames_data)
        logger.info(f"[reframe:{record_id}] MediaPipe: {len(tracked)} tracked frames")
        return tracked

    def _upload_and_encode(self, record, record_id, out_path, probe):
        """Step 5-6: Upload to GCS and transcode."""
        from reframe_filters import OUTPUT_CANVAS

        has_audio = probe.get("has_audio", True)
        ar = getattr(record, "output_aspect_ratio", "9:16") or "9:16"
        _out_w, out_h = OUTPUT_CANVAS.get(ar, OUTPUT_CANVAS["9:16"])
        logger.info(f"[reframe:{record_id}] Uploading cropped video...")
        bucket = os.getenv("GCS_BUCKET")
        intermediate_uri = f"gs://{bucket}/reframes/{record_id}/cropped.mp4"
        deps.storage_svc.upload_from_file(out_path, intermediate_uri)

        self.update_status(record_id, "encoding", 75)
        if not deps.transcoder_svc:
            return intermediate_uri

        logger.info(f"[reframe:{record_id}] Starting Transcoder encode ({ar})...")
        # v2 hands a finished 1080-wide canvas (out_h per aspect ratio) — re-encode.
        job_name, output_uri = deps.transcoder_svc.reframe_encode(
            record_id,
            intermediate_uri,
            has_audio=has_audio,
            out_h=out_h,
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
