# Reframe Eval — Reference-Free Per-Run Quality Report

Status: built and live (see Status section below)
Related: [reframing-v2.md](reframing-v2.md) (the pipeline being evaluated)

## Context

Production reframes are **unseen videos with no ground truth** — there is no
human-labeled "correct crop per frame" or "who is speaking when" to grade against.
So quality evaluation must be **reference-free**: score the chosen framing against
*independent signals the pipeline already produces* (the raw detections and the
audio), not against labels.

The two things that matter:
1. **Correct letterboxing** — keep the important content in frame (don't cut
   people), without needless letterboxing (don't shrink content to bars when a
   tighter crop would do).
2. **Showing the person talking** — in dialogue, frame the active speaker.

Goal: emit an automatic **per-run report card** for every job, stored on the
record and surfaced in the UI/logs, that flags the failures we've actually seen
(cut subjects, over-letterbox, wrong/silent face, off-center) — a tripwire, not a
grade.

## Principle: score against signals that didn't decide the framing

The eval is only meaningful if it checks the output against an *independent* view.
Two independent signals are available per run:
- **All detections** (faces/persons), including ones the framing did NOT choose —
  so we can catch "we cut someone who was there."
- **Audio** (already extracted for diarization) — independent of the visual crop
  decision, so it can falsify "we're showing the talker."

Avoid circularity: e.g. "is the chosen face in frame" is ~guaranteed (we cropped
to it); instead measure whether *any* detected subject is cut, and whether the
*audio* agrees with who we're showing.

## Goal 1 — Letterboxing / framing metrics (geometry from detections + plan)

Computed from `tracked_frames` (faces/persons) + the plan's per-segment crop
window. No output download, no labels.

- **`face_cut_rate`** — fraction of sampled frames where a *detected* face bbox is
  clipped by the chosen crop edge. Direct "are we cutting people." (Catches the
  7:20 talker-cut.)
- **`subject_containment`** — fraction of frames where the tracked subject's bbox
  is fully inside the crop.
- **`over_letterbox_rate`** — fraction of letterboxed (16:9/1:1) segments where a
  *tighter* rung would still have contained the must-keep content → we letterboxed
  more than necessary. Separates "needed the bars" from "wasted screen." (Catches
  "always 16:9".)
- **`mean_letterbox_pct`** — time-weighted % of the 1080×1920 canvas that is blur
  bars (`1 - fg_h/1920` per segment). Context for the above.

## Goal 2 — "Showing the talker" metrics (audio ↔ video, label-free)

The independent signal is **audio**. Correlate the **framed face's mouth motion**
(MAR variance, already computed for ASD) with **speech presence** (voice-activity
detection, or the Chirp diarization speech intervals we already compute).

- **`av_sync_score`** — correlation, over time, between the framed face's mouth
  activity and audio speech presence. High = we show whoever is talking when they
  talk. Reference-free: audio never chose the crop. *The key ASD metric.*
- **`framed_speaker_active_rate`** — in multi-face/dialogue time, fraction where
  the framed face's mouth activity exceeds the talking threshold (vs parked on a
  silent listener).
- **`speaker_miss_rate`** — frames where audio indicates speech, an *off-frame*
  detected face has high mouth activity, but a *different* face is framed → showing
  the wrong person. (Catches the 14:00 wrong-face.)

## Stability / polish

- **`ar_changes_per_min`**, **`crop_jumps_per_min`** — excessive switching = janky.
- **`center_offset_p50/p90`** — face-x distance from crop center (the metric that
  corrected the Pichai claim).

## Report shape

Per segment + a per-run aggregate. Each metric carries a threshold → ✅ / ⚠️ / ❌,
plus the 2–3 worst-offending timestamps per failing metric (jump straight to the
bad moments). Example aggregate:

```
eval_report = {
  "letterbox":   {"face_cut_rate": 0.07, "over_letterbox_rate": 0.12,
                  "mean_letterbox_pct": 0.28, "flag": "ok"},
  "talker":      {"av_sync_score": 0.61, "framed_speaker_active_rate": 0.74,
                  "speaker_miss_rate": 0.18, "flag": "warn"},
  "stability":   {"ar_changes_per_min": 9, "center_offset_p90": 0.12},
  "worst":       [{"t": 840.0, "metric": "speaker_miss_rate", "detail": "..."}],
  "overall": "warn",
}
```

## Implementation sketch

- New stage `api/reframe_eval.py` (pure-ish): `evaluate(plan, tracked_frames,
  person_frames, speech_intervals, src_w, src_h, duration) -> dict`.
  - Letterbox/containment/stability: pure geometry over plan + detections.
  - AV-sync: needs per-track MAR over time (have it) + speech intervals (from
    diarization, or a cheap VAD on the extracted wav).
- Worker calls it before `render_plan`, stores `eval_report` on the record
  (`models_records.ReframeRecord`) so it's visible mid-job.
- Surface in the reframe output page (a small scorecard) and log the aggregate.
- Reuses already-collected data (detections w/ MAR, plan, audio, diarization) — no
  re-decode of the output needed; cheap stage.

### Output-pixel check (`api/reframe_render_check.py`)

The geometry eval above never decodes the rendered video, so it can't see
FFmpeg/encode defects. A companion stage closes that: after `render_plan`,
`check_render(out_path, segments, …)` decodes a *sampled* set of output frames
(≤12, one per segment midpoint), runs face detection on them, and scores them
against what the plan predicted — then folds a `render` block into `eval_report`
and rolls its flag into `overall`. cv2/ffmpeg/MediaPipe-bound (worker-only),
best-effort (never fails the job). The prediction comes from the plan, the
measurement from the decoded output, so they stay independent. Metrics:
- **`nonblank_rate`** — output frames with real content (catches black/garbled).
- **`face_present_rate`** — for face-framed samples, the subject is actually in
  the output (catches a vanished subject / wrong scene rendered).
- **`position_error_p90`** — detected face's output-x vs the predicted output-x
  (catches a wrong crop offset that the geometry eval / contract test missed).
- **`split_panel_fill_rate`** — both stacked split panels show a person (catches a
  broken `vstack`).
The plan→render *x(t)* contract (eval's `crop_left_px_at` ↔ the emitted FFmpeg
expression) is separately pinned by `test_render_eval_contract`.
- Runs on **every** production video → continuous, label-free quality signal, and
  the objective scoreboard to **tune** ASD/coverage thresholds against real
  footage instead of guessing.

## Local validation

Validate/measure inside the **worker Docker image** (Debian, has libGL/EGL/GLES +
ffmpeg + pinned opencv/mediapipe). The host venv lacks `libGLESv2`, so MediaPipe
degrades to Haar there and ffmpeg is absent — unreliable for CV measurement.

## Honest caveats

- These are **proxies**, not truth: bounded by detector quality (a missed face
  can't be scored as "cut"); `av_sync_score` degrades with background music /
  off-screen narration / overlapping speakers. The output-pixel check is bounded
  the same way — a missed face in the output reads as a (false) absence, so its
  thresholds are lenient and aggregate, not per-frame fatal.
- They are **directional and falsifiable** — reliably catch the four failures
  reported so far, plus gross render defects (black output, wrong crop offset,
  broken split panel). Treat the report as an automated tripwire + tuning
  scoreboard, not a quality grade.

## Status

Built and live (geometry + talker + stability + output-pixel check), persisted to
`eval_report`, surfaced in the output-page scorecard, logged per job. Remaining:

- Calibrate thresholds (`SPEAKER_MIN_ACTIVITY` / `SPEAKER_DOMINANCE`, coverage
  caps, and the render-check tolerances) against real labeled clips — currently
  hand-picked, directional defaults.
