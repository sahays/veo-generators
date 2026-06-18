# Reframe Service — v2 Design: Adaptive Letterboxing

Status: design / proposal
Supersedes the fixed-9:16 crop pipeline reviewed in [reframing-v1.md](reframing-v1.md).

## Goal

Reframe wide (16:9+) video for mobile, where **each scene chooses how much to crop
vs. letterbox** on a fixed portrait canvas — instead of force-cropping everything to
9:16. This preserves content that a hard 9:16 crop destroys:

- Wide on-screen text / logos (e.g. a full-width title card).
- Side-by-side podcasts / interviews (two people a hard crop can't both contain).
- Presentation / slide footage.

The output is always a single fixed **1080×1920 (9:16) canvas** — the mobile
full-screen viewport. "Per-scene aspect ratio" means the *inner content's* aspect
ratio varies; the leftover canvas is filled with the **same scene, full-height,
blurred** (the existing blurred-background effect, generalized). This is **adaptive
letterboxing**, not multi-aspect-ratio video (a file has one frame size; the player
viewport is fixed).

## Core principle: Gemini understands, CPU models locate

The single most important architectural rule:

> **Gemini emits semantic labels and names the entities that matter. A deterministic
> CPU model supplies the frame-accurate coordinates for those entities. Gemini's pixel
> coordinates never touch the crop math — only its judgments.**

Gemini knows the logo is essential and that a shot is "a 2-person interview where both
matter." It is *not* reliable for frame-accurate boxes, cut timestamps, or
who-is-speaking-right-now. Those come from CPU models.

### The precision stack

| Precision need | CPU / local model | Why not Gemini |
|---|---|---|
| Cut timestamps | **PySceneDetect** (ContentDetector) | Gemini timestamps drift ±0.5s; cuts must be frame-exact |
| Face bbox + position | **MediaPipe Face Detection** (already used) | per-frame geometry |
| Face landmarks / mouth | **MediaPipe FaceMesh** | needed for active-speaker |
| Active speaker | **Light-ASD / TalkNet**, or mouth-aspect-ratio (FaceMesh) × Chirp timing | Gemini can't sync lip motion to audio at frame level |
| Wide-text bbox | **DBNet / EAST / PaddleOCR-det** | precise logo/lower-third box; Gemini bbox too coarse |
| (sports) object | **YOLOv8n** | frame-accurate ball/player |

### Reconciliation pattern

Gemini returns a coarse hint → **snap it to the nearest CPU detection**:

- Gemini `"focus on the two hosts"` → match each host to a MediaPipe track by
  approximate x → use the **track's** exact bbox.
- Gemini `requires_full_width, text center-ish` → take **DBNet's** exact text bbox.
- Gemini `"Track A speaking 4–9s"` → **ASD** confirms the exact switch frame.

This also fixes v1 #1: track→entity mapping becomes a geometric match (label ↔ track
by position), not the broken track_id-order lookup.

## The unified filter

Generalize `build_blurred_bg_filter` so the inner aspect ratio is a parameter. Given
source `src_w×src_h`, canvas 1080×1920, chosen inner AR `aw:ah`:

```
crop_w  = round(src_h * aw/ah)      # how wide a slice of source we keep
crop_h  = src_h                     # always full height
fg_w    = 1080                      # foreground always fills canvas width
fg_h    = round(1080 * ah/aw)       # foreground height (bars are 1920 - fg_h)
y_off   = (1920 - fg_h) // 2

# background: full source scaled to COVER canvas, blurred
[0:v] scale=1080:1920:force_original_aspect_ratio=increase, crop=1080:1920, gblur=sigma=40 [bg]
# foreground: crop the slice (with pan x(t)), scale to inner size
[0:v] crop=crop_w:src_h:clip(x(t),0,src_w-crop_w):0, scale=1080:fg_h [fg]
[bg][fg] overlay=0:y_off [v]
```

This **subsumes both existing filters**:
- 9:16 → fg_h=1920, y_off=0 → foreground covers the canvas, no bars (`build_crop_filter`).
- 4:5 → fg_h=1350, y_off=285 → current `build_blurred_bg_filter`.

### Inner-AR rung ladder (1920×1080 source)

The inner-AR choice is a "how wide a slice do I keep" dial — more crop = bigger
content; less crop = smaller content with more blur.

| Inner AR | crop_w | % source width kept | bars (px) | use when |
|---|---|---|---|---|
| 9:16 | 608 | **32%** | 0 | single subject |
| 4:5 | 864 | 45% | 285 | subject + context |
| 1:1 | 1080 | **56%** | 420 | side-by-side (faces ~0.3/0.7 fit) |
| 16:9 letterbox | 1920 | **100%** | 656 | full-width text / logo / slide |

(9:16 keeps only ~32% of the width — that's *why* it chops wide logos and split
two-shots.)

## The decision function

Per segment, compute **required horizontal coverage** `C ∈ [0,1]` = fraction of
source width that must stay visible:

```
C_faces = (max_face_right - min_face_left) over the segment   # MediaPipe
C_text  = wide-text bbox width                                # DBNet / Gemini flag
C       = max(C_faces, C_text) + margin
```

Then pick the **lowest rung** whose `crop_w/src_w ≥ C`. Stability rules:

- **Snap only at cuts** — inner AR may change only at a PySceneDetect boundary. Never
  morph aspect mid-shot.
- **Hysteresis** — keep the previous segment's rung unless `C` exceeds it by a margin.
- **Minimum dwell** (≥~2s) — merge tiny segments so a quick insert doesn't resize.

Pan `x(t)` still runs *within* the chosen rung's `crop_w`, driven by `focal_path`.

## The layout axis

Inner-AR rung is one axis; **layout** is a second. Gemini *proposes* layout; the CPU
layer *validates* it (and has veto power, since it owns ground truth):

```
single          → crop to rung (9:16 … 4:5)
keep_both_wide  → letterbox rung (1:1, 16:9)
split           → two stacked panels        ← new
slide + speaker → PiP                        ← future
```

### Vertical split (stacked two-shot)

When two speakers are too far apart for any rung to keep them both at a decent size,
stack them: each panel is 1080×960 (half the canvas), so both appear **large**.

Use only when CPU confirms: two persistent tracks, wide separation, both active most
of the scene, roughly static shot. Gemini supplies the semantic "both matter"; CPU
supplies the frame-accurate per-face crops Gemini cannot.

Each panel is AR 1080:960 = 9:8 → `crop_w = 1080 × 9/8 = 1215`, full height, centered
on each track's x, scaled to 1080×960, stacked:

```
[0:v] crop=1215:1080:xA(t):0, scale=1080:960 [top]   # left person → top
[0:v] crop=1215:1080:xB(t):0, scale=1080:960 [bot]   # right person → bottom
[top][bot] vstack [v]                                 # optional 4px divider
```

No blurred background needed — the panels fill the canvas. Each panel gets its own
`focal_path` pan.

**Rules that keep it from looking broken:**
- **Stable assignment** — left→top, right→bottom; never swap mid-scene.
- **Near-static panels** — large deadzone; two simultaneously panning panels look busy.
- **Graceful degradation** — if one track drops out >N frames, fall back to
  active-speaker single-crop for that stretch.
- **Use sparingly** — stacking destroys eyeline/spatial continuity; gate behind a
  high-confidence "static 2-person dialogue" classification + min dwell.

## Pipeline

Two parallel analysis tracks (CPU-precision + Gemini-semantic) converge into a
per-segment plan, then a per-segment render.

```
STAGE 0  download + ffprobe (reject non-landscape)
            │ src dims, fps, dur
STAGE 1  PRECISION LAYER (CPU, all parallel)
            PySceneDetect → cuts[]      MediaPipe → face tracks (per-frame)
            Chirp → speaker turns       DBNet → text bboxes    ASD → speaking[]
            │ cuts[] define segments
STAGE 2  SEMANTIC LAYER (Gemini, given the cut list)
            per segment: scene_type, layout proposal, entities,
            requires_full_width, both_speakers_active
            │ labels (the "what")
STAGE 3  RECONCILE + DECIDE (CPU brain, per segment)
            • match Gemini entities → CPU tracks (geometric)
            • C = max(C_faces, C_text)
            • CPU validates layout (veto power)
            • pick layout + inner-AR rung
            • hysteresis + min-dwell (merge tiny segments)
            │ List[SegmentPlan]
STAGE 4  PAN PATHS (focal_path, per segment / per panel)
            scene-bounded smoothing → x(t) per crop
STAGE 5  RENDER (FFmpeg, per segment, parallel)
            layout-specific filtergraph → 1080×1920 canvas
STAGE 6  concat -c copy
STAGE 7  upload + transcode
```

Stage 1 runs concurrently (independent passes over the same file). Gemini (Stage 2)
is the one barrier — it needs the cut list so it labels the *same* segments the CPU
found.

### The object that flows through it

Stage 3's output is the spine; everything downstream is a pure function of it:

```python
SegmentPlan = {
  "start": 12.40, "end": 20.85,          # frame-accurate, from PySceneDetect
  "layout": "split",                     # single | keep_both | split | pip
  "inner_ar": None,                      # e.g. (1,1) for keep_both; None for split
  "crops": [                             # 1 crop for single/keep_both, 2 for split
    {"track_id": 3, "crop_w": 1215, "keypoints": [(t,x,y), ...]},
    {"track_id": 7, "crop_w": 1215, "keypoints": [(t,x,y), ...]},
  ],
  "reason": "2 persistent tracks, sep=0.38, both active 0.7",  # debug
}
```

### Worked transition (1920×1080 source)

- **A [0–12.4s] single host** — MediaPipe: one track x≈0.52, span 0.12 → C≈0.2 →
  **9:16 full-bleed**, no bars.
- **cut 12.40s → B [12.4–20.85s] two guests** — tracks at 0.31/0.69, C≈0.55, Gemini
  `side_by_side` + podcast default "keep both" → **1:1** (or **split** if separation
  is extreme). Foreground snaps to a centered box at the cut; blurred bg stays
  continuous behind it.
- **cut 20.85s → C [20.85–end] title card** — no faces; Gemini `requires_full_width`,
  DBNet bbox spans 0.05–0.95 → C≈0.95 → **16:9 letterbox**. Logo fully readable —
  the exact case v1 chops.

## Maps onto existing code

| Existing | v2 change |
|---|---|
| `workers/reframe_processor.py` | reorder to the stage flow above |
| `api/mediapipe_detection.py` scan/track | reuse; **`merge_scenes_with_tracks` deleted**, replaced by Stage 3 |
| `api/gemini_service.py` `analyze_video_scenes` | extend schema (consume cuts; emit layout / coverage / wide-text) |
| `api/reframe_filters.py` | generalize to parametric inner-AR + add `vstack` split builder |
| `api/focal_path.py` `smooth_focal_path` | unchanged; now called per segment (fixes v1 #2 for free) |
| `api/reframe_service.py` `execute_reframe` | becomes `render_plan(segments)`: iterate, pick filtergraph, render, concat (existing chunk infra, now scene-keyed) |
| **new** `api/scene_detect.py` | PySceneDetect wrapper |
| **new** `api/reframe_plan.py` | Stage 3 reconcile + decide |
| **new** `api/text_detect.py`, `api/active_speaker.py` | phase 2 precision |
| `api/reframe_strategies.py` | config feeds **dwell time + layout bias** (finally load-bearing → fixes v1 #3/#4) |

## How it resolves v1 issues

- **#1 (Track A mis-map)** → geometric entity matching in Stage 3.
- **#2 (cuts discarded in smoothing)** → segments *are* scenes; cuts are first-class.
- **#3/#4 (dead prompt + cv_strategy config)** → content-type config drives dwell /
  layout bias and per-segment behavior; remove the unused focal-points path.
- **#5 (Gemini cost untracked)** → carries over unchanged; fix independently
  (accumulate scene-analysis usage).

## Next steps (phased build plan)

Ship value early; don't build the split renderer before letterboxing is solid.

**Phase 0 — v1 cleanup (prereq).** Fix v1 #1, #2, #5. These are required foundations
(#2 especially) and are small. Do this first regardless of v2 timeline.

**Phase 1 — adaptive letterbox MVP (no new CPU models).**
1. Add `scene_detect.py` (PySceneDetect) → frame-accurate cuts.
2. Generalize `reframe_filters` to the unified parametric filter.
3. Re-key the chunker to scene boundaries; render per segment + concat.
4. Stage 3 with only `single` + `keep_both` using existing MediaPipe + Gemini.
5. Extend Gemini schema: `requires_full_width`, coarse must-keep bbox, `layout`.
6. Decision function: `C` → rung, with hysteresis + min-dwell.
   - *Deliverable:* full-width text/logos and split podcasts stop getting chopped.

**Phase 2 — precision detectors.**
7. `text_detect.py` (DBNet/PaddleOCR-det) → precise wide-text bbox (replaces trusting
   Gemini's box; this is the riskiest accuracy gap).
8. `active_speaker.py` (Light-ASD or FaceMesh mouth-AR × Chirp) → precise speaker
   switches for cut-vs-keep decisions.

**Phase 3 — split-screen layout.**
9. `vstack` split builder + per-panel pan.
10. Layout validation + graceful degradation (track-dropout fallback).
11. Gate behind high-confidence "static 2-person dialogue" + dwell.

**Phase 4 — PiP / auto-layout (slide + speaker).** Only if warranted; this is a
distinct, larger feature.

### Open decisions

- **Cut authority:** PySceneDetect owns boundaries, Gemini labels within them
  (recommended) vs. Gemini proposes / PySceneDetect refines (messier). Pick the former.
- **Two-shot default:** per content type — podcasts lean "keep both / split"; news/
  promos may prefer active-speaker cut.
- **Delivery vs. canvas:** one 9:16 deliverable with adaptive inner content, or
  multiple per-platform canvases (4:5 feed, 1:1 square)? Keep these axes separate.
- **CPU model footprint:** ASD/DBNet/YOLO add worker CPU + cold-start cost; confirm
  the worker image and per-job latency budget before committing to phase 2.
