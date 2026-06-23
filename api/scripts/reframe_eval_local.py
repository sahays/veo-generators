#!/usr/bin/env python3
"""Local harness to run the reframe pipeline + reference-free eval on a clip.

Mirrors workers/reframe_processor._run_ai_reframe end-to-end, but on a LOCAL
file, and prints/saves the eval report (api/reframe_eval.evaluate). Meant to be
run inside the worker Docker image (ffmpeg + libGL/EGL + mediapipe present).

Detection + plan + eval run with no cloud. Gemini scene labels and Chirp speech
turns (which power the talker metrics) are OPTIONAL:
  --gcs-uri gs://...   enable Gemini scene analysis (richer plan)
  --diarize            enable Chirp diarization for speech intervals (needs
                       --gcs-uri for the source and a writable GCS_BUCKET)
  --speech-json FILE   inject speech intervals [{start_sec,end_sec}] instead

Usage (inside container):
  python api/scripts/reframe_eval_local.py /tmp/ashley.mp4 --outdir /tmp/eval
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "workers"))


def _gemini_scenes(gcs_uri, track_summary, chirp_context):
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
        print(f"[eval-local] Gemini unavailable ({e}); face-only plan")
        return []


def _chirp_speech(video, name, duration):
    """Run Chirp diarization → [{start_sec,end_sec}] speech intervals.

    Builds only Storage + Diarization (not the full deps graph) so a missing
    Gemini/Vertex cred doesn't block the talker signal.
    """
    try:
        from diarization_service import DiarizationService, extract_audio
        from storage_service import StorageService

        bucket = os.getenv("GCS_BUCKET")
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
        if not (bucket and project):
            print("[eval-local] need GCS_BUCKET + GOOGLE_CLOUD_PROJECT for Chirp")
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
        print(f"[eval-local] Chirp: {len(segs)} speaker turns")
        return [{"start_sec": s["start_sec"], "end_sec": s["end_sec"]} for s in segs]
    except Exception as e:  # noqa: BLE001
        print(f"[eval-local] Chirp unavailable ({e}); talker av-sync will be null")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="local landscape video file")
    ap.add_argument("--gcs-uri", default="", help="gs:// URI to enable Gemini labels")
    ap.add_argument("--diarize", action="store_true", help="run Chirp for speech turns")
    ap.add_argument("--speech-json", default="", help="speech intervals JSON file")
    ap.add_argument("--outdir", default="/tmp/eval")
    ap.add_argument("--sample-fps", type=float, default=1.0)
    args = ap.parse_args()

    from mediapipe_detection import scan_video_detections, track_faces
    from reframe_eval import evaluate
    from reframe_plan import attach_keypoints, reconcile
    from reframe_service import ffprobe_video
    from scene_detect import detect_cuts

    from _reframe_helpers import format_track_summary

    os.makedirs(args.outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(args.video))[0]

    probe = ffprobe_video(args.video)
    w, h, dur = probe["width"], probe["height"], probe["duration"]
    print(
        f"[eval-local] {name}: {w}x{h} {dur:.1f}s audio={probe.get('has_audio', True)}"
    )

    cuts = detect_cuts(args.video)
    det = scan_video_detections(args.video, sample_fps=args.sample_fps)
    tracked = track_faces(
        [{"time_sec": f["time_sec"], "faces": f["faces"]} for f in det]
    )
    persons = [{"time_sec": f["time_sec"], "persons": f["persons"]} for f in det]
    track_summary = format_track_summary(tracked)
    print(f"[eval-local] {len(cuts)} cuts, {len(tracked)} sampled frames")

    # Optional cloud signals.
    speech = []
    if args.speech_json:
        speech = json.load(open(args.speech_json))
    elif args.diarize:
        speech = _chirp_speech(args.video, name, dur)
    scenes = _gemini_scenes(args.gcs_uri, track_summary, "")

    plan = reconcile(scenes, tracked, cuts, w, h, dur, person_frames=persons)
    attach_keypoints(plan, probe["fps"])
    print("\n[eval-local] === DECISION LOG ===")
    for s in plan:
        print(f"  [{s['start']:6.2f}-{s['end']:6.2f}] {s['reason']}")

    report = evaluate(plan, tracked, persons, speech, w, h, dur)
    out = os.path.join(args.outdir, f"{name}.eval.json")
    json.dump(report, open(out, "w"), indent=2)

    print("\n[eval-local] === EVAL REPORT ===")
    print(json.dumps(report, indent=2))
    print(f"\n[eval-local] wrote {out}")


if __name__ == "__main__":
    main()
