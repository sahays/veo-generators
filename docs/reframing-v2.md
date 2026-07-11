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

The output canvas is **selectable per job** (`output_aspect_ratio`): **9:16 →
1080×1920** (the mobile full-screen viewport) or **3:4 → 1080×1440** (a taller feed
format). Width is always 1080; only the height changes. Whichever canvas is chosen,
it is *fixed for that job* — "per-scene aspect ratio" means the *inner content's*
aspect ratio varies across the canvas's rung ladder; the leftover canvas is filled
with the **same scene, full-height, blurred** (the existing blurred-background
effect, generalized). This is **adaptive letterboxing**, not multi-aspect-ratio
video (a file has one frame size; the player viewport is fixed). Both canvases run
the *same* adaptive pipeline — only their rung ladders differ (see below).

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
content; less crop = smaller content with more blur. Each canvas has its own ladder
(`RUNGS_BY_CANVAS` in `reframe_rungs.py`); the tightest rung equals the canvas
aspect (full-bleed, 0 bars).

**9:16 canvas (1080×1920):**

| Inner AR | crop_w | % source width kept | bars (px) | use when |
|---|---|---|---|---|
| 9:16 | 608 | **32%** | 0 | single subject |
| 4:5 | 864 | 45% | 285 | subject + context |
| 1:1 | 1080 | **56%** | 420 | side-by-side (faces ~0.3/0.7 fit) |
| 16:9 letterbox | 1920 | **100%** | 656 | full-width text / logo / slide |

(9:16 keeps only ~32% of the width — that's *why* it chops wide logos and split
two-shots.)

**3:4 canvas (1080×1440):** same adaptive logic, shorter canvas — the ladder is
`[(3,4), (1,1), (16,9)]`.

| Inner AR | crop_w | % source width kept | bars (px) | use when |
|---|---|---|---|---|
| 3:4 | 810 | **42%** | 0 | single subject (full-bleed) |
| 1:1 | 1080 | **56%** | 360 | side-by-side |
| 16:9 letterbox | 1920 | **100%** | 832 | full-width text / logo / slide |

(3:4 full-bleed keeps ~42% of the width — a little more than 9:16's 32%, since the
canvas is less tall.)

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
split           → two stacked panels        ← done (Phase 3)
slide + speaker → PiP                        ← won't do (Phase 4)
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

**Phase 0.5 — validation spike (gate before building anything).**

This architecture is a design, not a validated system. Two assumptions are
load-bearing and *unproven* on real footage; if either fails, the approach needs
rethinking. Spend days here, not weeks, before committing to Phase 1.

Build a throwaway script (no integration, no UI) on **~10 real clips** spanning the
edge cases: full-width text/logo, side-by-side podcast, presentation slides, plain
single talking head, and fast-cut promo. Render each and eyeball it. Measure only:

1. **Does `C` (required coverage) trigger correctly?** — letterbox fires on the wide
   cases (logo/two-shot/slide) *without* false-triggering on the simple ones
   (talking head should stay full-bleed 9:16). This tests whether `C_faces` /
   `C_text` are reliable signals at all.
2. **Do cut-snapped transitions look acceptable to a human?** — the "snap at cut,
   no morph" aesthetic is an unverified claim. Watch the AR changes; they must read
   as intentional, not janky.

Secondary check: how coarse is Gemini's wide-text bbox? If it can't locate a logo
well enough to drive `C_text`, that confirms DBNet (Phase 2, step 7) is required, not
optional — pull it earlier.

**Pass:** both criteria hold → architecture validated where it matters; proceed to
Phase 1. **Fail:** `C` is noisy or transitions look bad → stop and rethink the signal
or the snap model before writing production code. Cost of failing here is days; cost
of discovering it in Phase 1 is weeks.

**Phase 1 — adaptive letterbox MVP (no new CPU models).**
1. Add `scene_detect.py` (PySceneDetect) → frame-accurate cuts.
2. Generalize `reframe_filters` to the unified parametric filter.
3. Re-key the chunker to scene boundaries; render per segment + concat.
4. Stage 3 with only `single` + `keep_both` using existing MediaPipe + Gemini.
5. Extend Gemini schema: `requires_full_width`, coarse must-keep bbox, `layout`.
6. Decision function: `C` → rung, with hysteresis + min-dwell.
   - *Deliverable:* full-width text/logos and split podcasts stop getting chopped.

**Phase 2 — precision detectors. ✅ Done.**
7. ✅ `text_detect.py` → precise wide-text coverage. Implemented as classical
   OpenCV morphology (gradient → Otsu → glyph contours → line grouping with a
   density guard) rather than DBNet/PaddleOCR: zero model download, no new
   dependency, no cold start — the v2 "CPU model footprint" open decision
   resolved in favour of the lightweight option. Gemini's coarse `requires_full_width`
   flag is reconciled with the measured extent in `reframe_plan.reconcile_text_coverage`
   ("Gemini understands, CPU locates"): the measurement refines Gemini's blanket
   1.0 down to the real text width (less needless letterbox) and can self-trigger
   on confidently-wide text Gemini missed, while Gemini remains the floor when the
   detector is blind. If precision proves insufficient on real footage, swap the
   detector internals for DBNet/EAST behind the same interface.
8. ✅ `active_speaker.py` (FaceMesh mouth-AR via MediaPipe FaceLandmarker) →
   per-face mouth-aspect-ratio; the speaker decision (variance dominance) lives in
   `reframe_plan.pick_active_speaker`.

**Phase 3 — split-screen layout. ✅ Done.**
9. ✅ `reframe_filters.build_split_filter` / `split_panel_geometry` — two
   full-height source slices, each panned to follow its subject, scaled to
   half-canvas panels and `vstack`ed (no blurred bg; panels fill the canvas).
   Renderer dispatches `layout=="split"` in `reframe_service._render_segment`.
10. ✅ Graceful degradation by *strict gating* rather than mid-segment fallback:
    `reframe_plan._split_crops` requires both tracks present in ≥ `SPLIT_MIN_FRAC`
    (0.80) of frames, so a dropout can't occur inside a qualifying segment —
    simpler and more predictable than switching layout mid-shot. Assignment is
    geometric and stable (left→top, right→bottom; never swaps). `reframe_eval`,
    `_merge_short`, the diagnostic overlay, and the plan summary all handle the
    `inner_ar=None` split shape; eval scores both panels (containment per panel,
    a face cut only if outside *every* panel, talker active if either panel shows
    the speaker).
11. ✅ Gated behind high-confidence static two-person dialogue: separation ≥
    `SPLIT_MIN_SEPARATION` (0.45), near-static (`SPLIT_MAX_MOTION` 0.06), dwell ≥
    `SPLIT_MIN_DWELL` (3s), scene_type dialogue / side_by_side, and only when ASD
    found no dominant single speaker (otherwise single-follow wins).

**Phase 4 — PiP / auto-layout (slide + speaker). ❌ Won't do.** Picture-in-picture
for slide-plus-speaker is a distinct, larger feature with its own layout, scaling,
and placement logic, and the adaptive-letterbox + split layers already cover the
high-value reframe cases (wide text/slides letterbox cleanly; two-shots split or
keep-both). Not planned; revisit only if real usage shows a concrete need.

### Open decisions

- **Cut authority:** PySceneDetect owns boundaries, Gemini labels within them
  (recommended) vs. Gemini proposes / PySceneDetect refines (messier). Pick the former.
- **Two-shot default:** per content type — podcasts lean "keep both / split"; news/
  promos may prefer active-speaker cut.
- **Delivery vs. canvas:** *resolved* — the output canvas is selectable per job
  (`output_aspect_ratio`: 9:16 or 3:4), each running the same adaptive pipeline on
  its own rung ladder. Still single-output per job (one chosen canvas, not several
  at once); adding more canvases (4:5 feed, 1:1 square) is just two more dict
  entries (`OUTPUT_CANVAS` + `RUNGS_BY_CANVAS`) plus a selector option.
- **CPU model footprint:** ASD/DBNet/YOLO add worker CPU + cold-start cost; confirm
  the worker image and per-job latency budget before committing to phase 2.

---

## Addendum — 2026-07-10 durable-fix overhaul (Phases 0–5)

Supersedes parts of the pipeline above. The dense Gemini scene pass shown in the
original Stage-2 diagram was retired (commit 0d57d70); this addendum documents
what replaced it and the perception/decision fixes shipped together, all
env-flag-gated with rollback via Cloud Run env flip.

**Root causes fixed** (all verified at file:line before the change):
1. Perception starvation — 1 fps detection, selfie-range BlazeFace, no-gap
   greedy tracker → 6% track coverage on a 93-cut trailer → blind center crops.
2. Prominence = `max(frac)` — face size never entered the subject pick.
3. Text policy — "letterbox for ANY readable text" + coverage-default-1.0 +
   forced one-rung widening + broad harmonize; eval exempted gemini_text
   letterbox from `over_letterbox_rate`, hiding the failure.
4. MAR speaker path unreachable (needed ≥2 faces in one 1 fps sample, then
   4 samples + 2.5× dominance inside a ≤5 s segment).
5. No regression harness — fixes oscillated (crop↔letterbox flipped ≥7×).

**What changed:**
- **Truth layer**: every job dumps `reframes/{id}/detections.json.gz` (raw
  pipeline inputs); `api/reframe_replay.py` replays a fixture deterministically;
  `api/tests/test_reframe_regression.py` gates metric drift against committed
  `baselines.json` (`api/scripts/build-reframe-fixture.py` builds/rebaselines).
  Eval gained a `failing` block (which metric drove overall), plan-shape
  counters, and a `perception` block that FAILS the report when detection
  silently degrades (Haar fallback / zero frames — both shipped before).
  Replay must stamp cluster keys (`cluster_escalations(collect_escalation_points(...))`)
  before `apply_verdicts` — recorded verdicts carry `<key>#t<start>` cluster keys,
  so without it every verdict silently drops and the replayed plan is
  verdict-free (caught 2026-07-10 by the legacy-vs-new A/B faithfulness check;
  baselines rebaselined once for the fix).
- **Perception** (`REFRAME_DETECT_FPS=4`, `REFRAME_FACE_MODEL=both`,
  `REFRAME_TRACKER=v2`): short+full-range BlazeFace NMS-merged; tracker with
  scene-cut reset, ~1 s gap tolerance, IoU+center+appearance cost; MAR on every
  detected face (unlocks the single-face speaker pin).
- **Fused prominence** (`REFRAME_PROMINENCE=fused`):
  `(0.5+0.5·conf)·√frac·(w/max_w)·center_prior·speak_mult` replaces `max(frac)`
  at every pick site. Equal-group needs prom ratio ≥ 0.75; the 0.6–0.75 band
  escalates `subject_choice`; below 0.6 one face simply dominates.
- **Per-line text regions**: `text_detect.persistent_text_regions` clusters
  lines across frames and classifies corner/persistent/small regions as
  watermark `bug`s that can never drive letterbox; conflict + required coverage
  computed from the offending regions only (union-band inflation is dead).
- **Whole-video semantic pass** (`REFRAME_SEMANTIC_PASS`, default off;
  `REFRAME_SEMANTIC_MODEL` default gemini-3.1-flash-lite): one video+audio call
  (`api/reframe_semantic.py` + `analyze_video_semantics`) returns per-shot
  CATEGORICAL judgments — content kind, text importance
  (essential/contextual/incidental), speaker screen positions. No coordinates,
  no coverage floats (the 0d57d70 lesson is structural: the schema has no
  numeric spatial field). **Two-key letterbox lock**: semantic importance AND a
  CPU-measured band, folded into C *before* the rung DP. `content_kind`
  branches replace the text/no-subject/weak-subject escalations; the legacy
  escalation path survives untouched as the fallback ladder (a failed pass =
  `scenes=[]` = today's exact behavior), and `subject_choice` remains as a thin
  image-mode escalation.
- **Speaker join**: Chirp decides WHO/WHEN, the semantic pass says WHERE that
  speaker appears (`offscreen` suppresses speaker-centering — the
  voiceover-poster hijack class), MAR (4 fps, speech-gated) validates or
  overrides. Vision-only MAR pinning now happens ONLY when no diarization
  exists at all — mouth motion in a diarized-silent window is chewing, not
  speech.

**Threshold recalibration still owed** (on fixtures, not by hand): FACE_CONF_MIN
(was tuned on short-range scores), SPEAKER_MIN_ACTIVITY/SPEAKER_DOMINANCE (MAR
distributions at 4 fps), STABLE_FRAC (on healthy tracks). Light-ASD remains the
deliberate escape hatch if framed_speaker_active_rate stays <0.4 on podcast
fixtures after the MAR fixes.

## Addendum — 2026-07-11 active picture area + subject-aware person pick

Diagnosed from production rf-yw9w9uk5 (Spider-Man: Brand New Day 4K trailer,
old pipeline), scene 2:20–2:30: (a) the source is a 2.39:1 scope picture inside
the 16:9 container — ~26% of every frame is baked black bars nothing detected,
so every crop kept them (output picture filled only ~74% of the canvas, and all
rung/width math reasoned about padding); (b) with no detectable face, the
person fallback picked the LARGEST box per frame — an out-of-focus foreground
guard's back — cropping Spider-Man (left, story subject) fully out of frame.

- **Active picture area** (`api/reframe_active_area.py`): per-frame max-luma
  row/col profiles over ~24 sampled frames → a bar row is dark in ≥85% of
  samples (not ALL: this very trailer is scope for 95% of its runtime with a
  full-bleed end slate — those minority samples come back as `outlier_times`,
  and segments in those shots render untrimmed via `src_full_frame`; >15%
  disagreement = mixed-format source → no trim). Per-side guards (≥2%, ≤35%,
  keep ≥50% area; any bright pixel in a row keeps it — baked subtitles/billing
  blocks stop the trim). The WHOLE pipeline then runs in
  active-picture coordinates: detection/text scans slice frames before
  inference, planner/eval get active dims as src_w/src_h, Pass-2 thumbnails are
  sliced, and the renderer prepends one `crop=` (`crop_prefilter`) per filter
  chain. Fixtures persist `active_area`; replay honors it (absent = full frame,
  so the existing corpus is byte-identical). Observability:
  `reframe_summary.active_area` + eval `perception.active_area`.
- **Subject-aware person pick** (`reframe_signals._person_groups` /
  `_pick_person_group`): person detections (no track ids) cluster by
  x-interval IoU ≥ 0.3; the subject group is chosen lexicographically —
  mostly-inside the semantic subject's third (when the scene carries
  `active_subject`), ever-shows-a-face (frontality: backs of heads don't carry
  scenes), then size. The chosen group's OWN series feeds the crop and the
  focal points (`x_target` re-picks the group at focal time), killing the
  per-frame largest-box flicker. `REFRAME_PROMINENCE=frac` restores legacy.
  One-time rebaseline: rf-piemrxjm center_crop_segments 7→8 — a 5-frame crowd
  window whose old "person" was two DIFFERENT people stitched together
  (x=0.14→0.64); the new pick is honest (best subject too sparse → center),
  and both render pixel-identical 16:9 full-width.
- **Eval tripwire** `subject_mismatch_segments`: person/center segments whose
  crop window entirely excludes the semantic subject's third (the class
  containment can't see — it grades the box the picker chose). Advisory
  (`failing` entry, not rolled into `overall`).
