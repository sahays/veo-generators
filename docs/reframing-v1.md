# Reframe Service — Review & Analysis (v1)

Review date: 2026-06-18

Converts landscape (16:9) video to portrait (9:16) by intelligently panning a
crop window to follow the subject.

## Pipeline

The pipeline (`workers/reframe_processor.py`):

1. **Download + probe** (`ffmpeg_runner.ffprobe_video`) → reject non-landscape sources
2. **Diarize** (Chirp 3, optional per content type) → "who speaks when"
3. **MediaPipe** face detection at 0.5fps (`mediapipe_detection.scan_video_faces` → `track_faces`) → tracked face positions
4. **Gemini** scene analysis (`gemini_service.analyze_video_scenes`) → per-scene "who to focus on" hints
5. **Merge** Gemini scenes + MediaPipe tracks (`mediapipe_detection.merge_scenes_with_tracks`) → raw focal points
6. **Smooth** (`focal_path.smooth_focal_path`) → velocity-limited Catmull-Rom pan path
7. **FFmpeg** crop+pan (`reframe_filters.py` / `reframe_service.py`) → chunked & parallelized
8. **Upload + Transcoder** encode → final output

### Key files

| File | Role |
|------|------|
| `api/reframe_service.py` | FFmpeg crop/pan orchestration, chunking, concat |
| `api/reframe_filters.py` | Pure FFmpeg filter-string generation (9:16 crop + 4:5 blurred-bg) |
| `api/reframe_strategies.py` | Content-type prompt templates + processing params |
| `api/focal_path.py` | Pure-math focal-point smoothing |
| `api/mediapipe_detection.py` | Face detect/track + scene↔track merge |
| `api/routers/reframe.py` | FastAPI router (`/api/v1/reframe`) |
| `workers/reframe_processor.py` | Job orchestration (the live pipeline) |
| `workers/_reframe_helpers.py` | Diarization/track → Gemini context formatting |

## Strengths

The architecture is well-factored: pure string-building (`reframe_filters`), pure
math (`focal_path`), pure formatting (`_reframe_helpers`), and a thin orchestration
layer. Standouts:

- **`_build_balanced_expr`** — builds an O(log n) `if`-tree to dodge FFmpeg's
  ~100-level expression-parser recursion limit. Sharp, non-obvious fix.
- **Parallel chunking** of long videos across FFmpeg workers with concat-demuxer
  reassembly.
- **Velocity limiting + deadzone + static-run collapse** is a thoughtful smoothing
  pipeline.
- Good defensive fallbacks throughout (no faces → center, no tracks → center, etc.).

## Issues, by severity

### 🔴 1. "Track A" hint resolves to the wrong face (correctness bug)

`_reframe_helpers.format_track_summary` tells Gemini that **Track A = the
most-visible track** (sorted by frequency descending):

```python
sorted_tracks = sorted(stable.items(), key=lambda kv: -len(kv[1]))
label = chr(ord("A") + i)  # A = most frequent
```

But `mediapipe_detection._pick_track` resolves "Track A" by **track_id order
within the current frame**:

```python
return sorted(tracks, key=lambda t: t["track_id"])[idx]  # idx 0 = lowest track_id
```

Lowest `track_id` = first-detected face, which is *not* the most-visible track. So
when Gemini says "focus on Track A" (e.g., the host who's on-screen most), the merge
can pick a different person. For 2-person podcast/interview content — the exact case
this is built for — the active speaker gets mis-framed. The code comment even admits
"*Sort by track_id frequency isn't available here*."

**Fix:** thread the global frequency-ranked label→track_id mapping from
`format_track_summary` into the merge instead of recomputing locally by track_id.

### 🔴 2. Scene cuts are discarded during smoothing → glides across hard cuts

`reframe_processor._smooth` hardcodes `scene_changes=[]`:

```python
keypoints = smooth_focal_path(focal_points=focal_raw, scene_changes=[], ...)
```

`focal_path.smooth_focal_path` is fully built to snap framing at scene boundaries
(`_build_scene_boundaries`, `_split_by_scenes`), but it's fed an empty list, so the
whole video is treated as one continuous segment. Combined with the velocity limiter,
a hard cut between two speakers at x=0.3 and x=0.7 (Δ0.4) at the podcast velocity of
0.10/s takes **~4 seconds to pan across** — a slow drift across an instant cut,
instead of a snap. Gemini returns scene `start_sec`/`end_sec` (stored as
`gemini_scenes`); those boundaries should be passed in as `scene_changes`.

### 🟠 3. Content-type prompt machinery is dead code

`reframe_strategies.py` builds rich per-type prompts (`BASE_REFRAME_PROMPT_TEMPLATE`
+ `CONTENT_TYPE_VARIABLES`: focal_strategy, sampling, audio, framing, extra_rules for
movies/sports/podcasts/etc.). These are consumed *only* by
`gemini_service.analyze_video_focal_points`, which **nothing calls**. The live
pipeline uses `analyze_video_scenes`, which uses the static `SCENE_ANALYSIS_PROMPT`
(no content-type guidance).

Net effect: selecting "sports" vs "podcasts" changes only
`max_velocity`/`deadzone`/`use_diarization` — the Gemini prompt is identical. The
carefully written per-type framing instructions never reach the model.

**Fix:** either wire the content-type variables into `analyze_video_scenes`, or delete
the dead path (`analyze_video_focal_points`, `resolve_prompt`, the focal-text
variables). Note this machinery has tests (`test_strategies.py`) giving false
confidence that it's active.

### 🟠 4. `cv_strategy` is also unused

Every `STRATEGY_CONFIG` entry has `cv_strategy` ("face"/"multi_face"/"motion"), but
`_run_mediapipe` always runs the same `scan_video_faces`. So "sports"
(`cv_strategy: motion`) still does face detection — useless for ball-tracking footage.
It's surfaced in `system.py` and the editor agent as if meaningful. Either implement
strategy branching or drop the field.

### 🟡 5. Gemini video-analysis cost isn't tracked

`_run_diarization` and `_upload_and_encode` accumulate diarization/transcoder costs,
and `_analyze_scenes` stores `result.usage` on the record — but no `accumulate_*_cost`
call exists for the Gemini scene analysis. Video tokens at `gemini-3.1-pro` are the
likely dominant cost of a reframe job, and they're invisible to cost tracking.

### 🟡 6. Chunked audio may drift on long videos

In `_build_reframe_cmd`, chunks use input seeking (`-ss` before `-i`) with
`-c:a copy`, then concat with `-c copy`. Input seek + stream-copy audio snaps to the
nearest audio packet, which can offset A/V per chunk and accumulate across the concat
join. Video is re-encoded so it's frame-accurate, but audio isn't. Verify sync on a
multi-chunk (long) clip; if it drifts, re-encode audio per chunk or use output seeking.

### 🟢 Minor

- **Odd crop width**: `build_crop_filter` → `crop_w = int(src_h * 9/16)` = 607 for a
  1080-tall source (odd). Harmless only because a `scale=1080:1920` follows in the
  same chain, but it's fragile.
- **No MediaPipe/scan timeout**: `scan_video_faces` decodes the full video
  frame-by-frame with no timeout — a long source could stall a worker slot.
- **No failing-step context on failure**: `mark_failed` records `str(e)` but not which
  stage; adding the failing step to the message would speed debugging.
- **`MAX_CONCURRENT` naming**: `_poll_cycle` runs `processor.process(record)`
  serially, so reframe jobs (minutes each) block the loop — the name implies
  parallelism that isn't there.

## Recommendation

Issues **#1 and #2 directly degrade output quality** on the service's core use case
(multi-speaker dialogue), and both are small, localized fixes. **#3/#4 are tech-debt
cleanup** — decide whether content-type should shape the prompt (high value) or delete
the dead machinery. Suggested priority: **#1 → #2 → #5 (cost visibility) → #3**.

## Next: v2

The v2 redesign (adaptive letterboxing — per-scene aspect ratio on a fixed canvas,
plus split-screen layouts) is specified in [reframing-v2.md](reframing-v2.md). It
absorbs v1 issues #1–#4 structurally: scene-bounded segments fix #2, geometric
entity matching fixes #1, and content-type config becomes load-bearing (#3/#4). Fix
#5 (Gemini cost tracking) independently — it carries over to v2 unchanged.
