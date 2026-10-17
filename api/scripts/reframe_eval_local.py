#!/usr/bin/env python3
"""Local harness to run the reframe pipeline + reference-free eval on a clip.

Mirrors workers/reframe_processor._run_ai_reframe end-to-end, but on a LOCAL
file, and saves the eval report (api/reframe_eval.evaluate). Meant to be
run inside the worker Docker image (ffmpeg + libGL/EGL + mediapipe present).
"""

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "workers"))

logger = logging.getLogger("reframe_eval_local")


def _log(msg: str, where: str = "reframe_eval_local") -> None:
    logger.info(
        msg,
        extra={
            "who": "reframe_eval_local",
            "where": where,
            "what": msg[:120],
            "why": "Local reframe evaluation harness",
            "how": "cli",
        },
    )


def _gemini_scenes(gcs_uri: str, track_summary: str, chirp_context: str) -> list:
    if not gcs_uri:
        return []
    try:
        import deps

        deps.init_services()
        context = "\n\n".join(filter(None, [chirp_context, track_summary]))
        result = asyncio.new_event_loop().run_until_complete(
            deps.ai_svc.analyze_video_scenes(
                gcs_uri=gcs_uri, mime_type="video/mp4", chirp_context=context
            )
        )
        return result.data.get("scenes", [])
    except Exception as e:  # noqa: BLE001 — degrade to face-only
        _log(f"[eval-local] Gemini unavailable ({e}); face-only plan", "_gemini_scenes")
        return []


def _chirp_speech(video: str, name: str, duration: float) -> list:
    """Run Chirp diarization → [{start_sec,end_sec}] speech intervals."""
    try:
        from diarization_service import DiarizationService, extract_audio
        from storage_service import StorageService

        bucket = os.getenv("GCS_BUCKET")
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
        if not (bucket and project):
            _log(
                "[eval-local] need GCS_BUCKET + GOOGLE_CLOUD_PROJECT for Chirp",
                "_chirp_speech",
            )
            return []
        storage = StorageService()
        diar = DiarizationService(project, location)
        audio_path = "/tmp/_eval_audio.wav"
        extract_audio(video, audio_path)
        audio_uri = f"gs://{bucket}/eval-local/{name}-audio.wav"
        storage.upload_from_file(audio_path, audio_uri)
        result = diar.transcribe_with_diarization(
            audio_gcs_uri=audio_uri,
            storage_svc=storage,
            record_id=f"eval-{name}",
            audio_duration=duration,
        )
        segs = result.get("speaker_segments", [])
        _log(f"[eval-local] Chirp: {len(segs)} speaker turns", "_chirp_speech")
        return [{"start_sec": s["start_sec"], "end_sec": s["end_sec"]} for s in segs]
    except Exception as e:  # noqa: BLE001
        _log(
            f"[eval-local] Chirp unavailable ({e}); talker av-sync will be null",
            "_chirp_speech",
        )
        return []


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="local landscape video file")
    ap.add_argument("--gcs-uri", default="", help="gs:// URI to enable Gemini labels")
    ap.add_argument("--diarize", action="store_true", help="run Chirp for speech turns")
    ap.add_argument("--speech-json", default="", help="speech intervals JSON file")
    ap.add_argument("--outdir", default="/tmp/eval")
    ap.add_argument("--sample-fps", type=float, default=1.0)
    return ap.parse_args()


def _resolve_speech(args: argparse.Namespace, name: str, dur: float) -> list:
    if args.speech_json:
        with open(args.speech_json) as f:
            return json.load(f)
    if args.diarize:
        return _chirp_speech(args.video, name, dur)
    return []


def main() -> None:
    args = _parse_args()
    from _reframe_helpers import format_track_summary
    from mediapipe_detection import scan_video_detections, track_faces
    from reframe_eval import evaluate
    from reframe_plan import attach_keypoints, reconcile
    from reframe_service import ffprobe_video
    from scene_detect import detect_cuts

    os.makedirs(args.outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(args.video))[0]
    probe = ffprobe_video(args.video)
    w, h, dur = probe["width"], probe["height"], probe["duration"]
    _log(
        f"[eval-local] {name}: {w}x{h} {dur:.1f}s audio={probe.get('has_audio', True)}",
        "main",
    )

    cuts = detect_cuts(args.video)
    det = scan_video_detections(args.video, sample_fps=args.sample_fps)
    tracked = track_faces(
        [{"time_sec": f["time_sec"], "faces": f["faces"]} for f in det]
    )
    persons = [{"time_sec": f["time_sec"], "persons": f["persons"]} for f in det]
    track_summary = format_track_summary(tracked)
    _log(f"[eval-local] {len(cuts)} cuts, {len(tracked)} sampled frames", "main")

    speech = _resolve_speech(args, name, dur)
    scenes = _gemini_scenes(args.gcs_uri, track_summary, "")
    plan = reconcile(scenes, tracked, cuts, w, h, dur, person_frames=persons)
    attach_keypoints(plan, probe["fps"])
    for s in plan:
        _log(f"  [{s['start']:6.2f}-{s['end']:6.2f}] {s['reason']}", "main")

    report = evaluate(plan, tracked, persons, speech, w, h, dur)
    out = os.path.join(args.outdir, f"{name}.eval.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    _log(f"[eval-local] wrote {out}: {json.dumps(report)}", "main")


if __name__ == "__main__":
    main()
