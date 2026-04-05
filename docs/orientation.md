# Orientation / Reframe Architecture

Intelligent landscape-to-portrait video reframing using a multi-stage pipeline that combines face detection (MediaPipe), scene understanding (Gemini), speaker diarization (Chirp 3), and smooth path synthesis to produce natural-looking cropped output via FFmpeg.

---

## Pipeline Overview

```
                         ┌─────────────────────────────────────────────────────┐
                         │                    FRONTEND                         │
                         │  ReframeWorkPage ──POST /reframe──▶ ReframeRecord   │
                         │  (select source, content type, options)   (pending) │
                         └──────────────────────┬──────────────────────────────┘
                                                │
                                                ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                              WORKER  (reframe_processor.py)                           │
│                                                                                       │
│  ┌──────────────┐   ┌──────────────────┐   ┌─────────────────────┐                    │
│  │  1. Download  │   │  2. Diarization  │   │  3. Face Detection  │                    │
│  │  & Probe      │──▶│  (Chirp 3)       │──▶│  & Tracking         │                    │
│  │  ffprobe      │   │  speaker segments │   │  (MediaPipe)        │                    │
│  └──────────────┘   └────────┬─────────┘   └──────────┬──────────┘                    │
│                              │                        │                               │
│                              ▼                        ▼                               │
│                    ┌──────────────────────────────────────────┐                        │
│                    │  4. Scene Analysis (Gemini 3.1)          │                        │
│                    │  video + diarization context + tracks    │                        │
│                    │  ──▶ scenes with active_subject hints    │                        │
│                    └───────────────────┬──────────────────────┘                        │
│                                       │                                               │
│                                       ▼                                               │
│                    ┌──────────────────────────────────────────┐                        │
│                    │  5. Merge Scenes + Tracks                │                        │
│                    │  Map active_subject ──▶ track positions  │                        │
│                    │  ──▶ focal_points [{t, x, y}]           │                        │
│                    └───────────────────┬──────────────────────┘                        │
│                                       │                                               │
│                                       ▼                                               │
│                    ┌──────────────────────────────────────────┐                        │
│                    │  6. Smooth Focal Path                    │                        │
│                    │  Catmull-Rom splines + velocity limit    │                        │
│                    │  + deadzone suppression ──▶ keypoints    │                        │
│                    └───────────────────┬──────────────────────┘                        │
│                                       │                                               │
│                                       ▼                                               │
│                    ┌──────────────────────────────────────────┐                        │
│                    │  7. FFmpeg Crop & Scale                  │                        │
│                    │  Piecewise-linear x(t) expressions       │                        │
│                    │  Parallel chunk processing                │                        │
│                    └───────────────────┬──────────────────────┘                        │
│                                       │                                               │
│                                       ▼                                               │
│                    ┌──────────────────────────────────────────┐                        │
│                    │  8. Transcode (Cloud Transcoder)         │                        │
│                    │  Encode to delivery formats ──▶ GCS      │                        │
│                    └──────────────────────────────────────────┘                        │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
                         ┌─────────────────────────────────────────────────────┐
                         │                    FRONTEND                         │
                         │  Polls status ──▶ ReframeOutputPage                 │
                         │  (side-by-side player, pipeline diagnostics)        │
                         └─────────────────────────────────────────────────────┘
```

---

## Processing Modes

| Mode | Output | Description |
|------|--------|-------------|
| **AI Reframe** | 9:16 (1080x1920) | Full pipeline — Gemini + MediaPipe + smooth path + FFmpeg crop |
| **Blurred Background** | 4:5 (1080x1350) | Cropped content centered over blurred scaled-up source |
| **Vertical Split** | 9:16 (1080x1920) | Simple 4:3 crop split into two halves stacked vertically |

---

## Content-Type Strategies

Each content type tunes the pipeline's behavior:

| Content Type | Max Velocity | Deadzone | Diarization | CV Strategy | Character |
|---|---|---|---|---|---|
| `movies` | 0.15 | 0.05 | yes | face | Smooth, cinematic pans |
| `documentaries` | 0.15 | 0.05 | yes | face | Smooth, narrator tracking |
| `sports` | 0.50 | 0.02 | no | motion | Fast, reactive tracking |
| `podcasts` | 0.10 | 0.08 | yes | multi_face | Very smooth, speaker focus |
| `promos` | 0.20 | 0.04 | no | face | Moderate, subject-focused |
| `news` | 0.12 | 0.06 | yes | multi_face | Steady, anchor tracking |
| `other` | 0.15 | 0.05 | yes | face | Balanced default |

---

## Key Modules

### API Layer

| File | Role |
|------|------|
| `api/routers/reframe.py` | REST endpoints — CRUD, retry, sources |
| `api/models.py` | `ReframeRecord`, `FocalPoint`, `SpeakerSegment` |
| `api/reframe_strategies.py` | Per-content-type prompt variables and processing params |
| `api/schemas/reframe-scenes-schema.json` | Gemini output schema (scenes with `active_subject`) |

### Processing Core

| File | Role |
|------|------|
| `workers/reframe_processor.py` | Orchestrator — runs all 8 stages sequentially |
| `api/mediapipe_detection.py` | Face detection, position-based tracking, scene-track merging |
| `api/diarization_service.py` | Chirp 3 speaker diarization (chunked for long videos) |
| `api/ai_helpers.py` | Gemini scene analysis prompts and calls |
| `api/focal_path.py` | Catmull-Rom interpolation, velocity limiting, deadzone |
| `api/reframe_filters.py` | FFmpeg filter string generation (crop, blur, split) |
| `api/reframe_service.py` | FFmpeg execution, chunk splitting, concatenation |
| `api/ffmpeg_runner.py` | Low-level FFmpeg/ffprobe subprocess wrapper |

### Frontend

| File | Role |
|------|------|
| `frontend/src/components/pages/ReframeWorkPage.tsx` | Create jobs, poll status, display results |
| `frontend/src/components/pages/ReframeOutputPage.tsx` | Pipeline diagnostics — prompt, chirp, gemini, mediapipe tabs |
| `frontend/src/lib/api.ts` | HTTP client (`api.reframe.*`) |

---

## Detection & Merging Strategy

The pipeline uses a **two-pass detection** approach:

1. **Bottom-up (MediaPipe)** — detects all faces frame-by-frame at 0.5 fps, then assigns persistent track IDs by matching positions across frames (`max_distance=0.15`).

2. **Top-down (Gemini)** — analyzes the full video with diarization context, returns scene boundaries and semantic `active_subject` hints (e.g. `"Track A"`, `"left"`, `"right"`, `"center"`, `"largest"`).

3. **Merge** — maps Gemini's semantic hints to MediaPipe track coordinates, producing `focal_points` with concrete `(x, y)` positions at each scene boundary.

---

## Path Smoothing

Raw focal points are noisy and would produce jarring pans. `focal_path.py` applies:

1. **Scene-aware segmentation** — reset interpolation at scene boundaries (no smoothing across cuts)
2. **Catmull-Rom splines** — cubic Hermite interpolation produces natural curves between focal points
3. **Velocity limiting** — caps pan speed per content type (e.g. 0.10 for podcasts, 0.50 for sports)
4. **Deadzone suppression** — ignores movements smaller than threshold to prevent micro-jitter
5. **Static run collapse** — removes redundant interior keypoints when position is unchanged

Output: keypoints at ~1 second intervals, ready for FFmpeg filter compilation.

---

## FFmpeg Filter Compilation

`reframe_filters.py` compiles keypoints into FFmpeg filter expressions:

- **9:16 crop**: `crop=W:H:clip(x(t),0,max_x),scale=1080:1920` where `x(t)` is a nested piecewise-linear expression: `if(lt(t,t1), lerp1, if(lt(t,t2), lerp2, ...))`.
- **Blurred background**: `filter_complex` with two streams — `[bg]` scaled + blurred source, `[fg]` cropped + scaled content, composited via `overlay`.
- **Vertical split**: crop left/right 4:3 sections, scale to half-height, stack with white divider.

Long videos are split into chunks (max 80 keypoints each) and processed in parallel, then concatenated.

---

## Status Lifecycle

```
pending ──▶ analyzing ──▶ processing ──▶ encoding ──▶ completed
   │            │              │             │
   └────────────┴──────────────┴─────────────┴──▶ failed
```

Progress updates are written to Firestore at each stage. The frontend polls every 2-3 seconds while the job is active.

---

## External Services

| Service | Purpose |
|---------|---------|
| **Firestore** | Job queue and record storage |
| **Google Cloud Storage** | Video/audio/output file storage |
| **Gemini 3.1** | Scene analysis and active subject identification |
| **Chirp 3 (Speech V2)** | Speaker diarization with timestamps |
| **Cloud Transcoder** | Final video encoding to delivery formats |
| **MediaPipe Tasks** | Face detection (with Haar cascade fallback) |
| **FFmpeg / ffprobe** | Video processing, probing, cropping, scaling |
