# VeoGen — System Design

This document drills into the *how*: the async job model, the data schema, request lifecycles per feature, the pricing/cost engine, scaling and failure behavior, and known trade-offs. For the high-level component map, read [ARCHITECTURE.md](./ARCHITECTURE.md) first.

---

## 1. Goals & Constraints

**Functional goals**
- Turn a text concept into a fully rendered, stitched video (the "production" pipeline).
- Offer derivative media tools on existing video: reframe, promo, aspect-ratio adapts, thumbnails, key-moments extraction.
- Provide a live conversational avatar and a master-only AI co-pilot ("Ask Aanya").
- Track and forecast cloud/AI spend per job.

**Non-functional constraints**
- Renders take **seconds to minutes** — far longer than an HTTP request should block.
- AI/media APIs are **expensive** — access must be gated and cost must be observable and forecastable.
- Operational simplicity is prioritized over maximal throughput (small-team, self-hostable on Cloud Run).
- Two regions in play: a Gemini/ADK region and an infrastructure region (Transcoder/Speech) — the design must keep them straight.

---

## 2. The Async Job Model

### 2.1 Why polling

Long renders cannot run inside the API request. The system uses a **database-as-queue** pattern: the job record's `status` field *is* the queue. The API writes `pending`; a separate worker polls for `pending`, claims and runs the job, and writes terminal status. This avoids a message broker entirely — at the cost of up to one poll interval of dispatch latency.

### 2.2 The dispatch loop (`workers/unified_worker.py`)

```
on startup:
    reclaim orphans  (reset records stuck in an in-flight status → pending)
loop forever:
    for processor in [reframe, promo, adapts, avatar]:
        records = processor.get_pending_records()       # Firestore query: status == "pending"
        for record in records[:MAX_CONCURRENT]:
            try:    processor.process(record)            # runs the full pipeline
            except: processor.mark_failed(record, err)
    sleep(WORKER_POLL_INTERVAL)                          # ~5s
```

- **Processors** are `JobProcessor` subclasses (`base_processor.py`) declaring a `name` and the Firestore update method to call. Each implements `get_pending_records()` and `process(record)`.
- **Sync↔async bridge** — processors are synchronous but the services they call are `async`. `base_processor._run_async()` runs the coroutine to completion, letting blocking media work (FFmpeg subprocess) and async SDK calls coexist.
- **Progress** — `update_status(id, status, progress)` writes incremental progress so the frontend's poller can render a progress bar; terminal states stamp a `completedAt` timestamp.
- **Temp files** — `TempFileManager` tracks scratch files (downloaded sources, intermediate clips) and cleans them up even on failure.

### 2.3 Concurrency & idempotency

- A single worker processes up to `MAX_CONCURRENT` jobs per cycle; scale horizontally by running more worker instances (each polls independently).
- **Claiming**: the current model is poll-and-process; with multiple workers there is a small race window where two workers could pick the same `pending` record. Status transitions and orphan reclaim mitigate duplicate/abandoned work; a stricter design would use a transactional claim (compare-and-set `pending → processing`). See §9 trade-offs.
- **Avatar turns** use a deterministic seed (`adler32(avatar.id)`) so re-running a turn yields a visually consistent avatar.

---

## 3. Data Model (Firestore)

All records live in Firestore Native-mode collections, namespaced with the service prefix (e.g. `veo_generators_productions`). Media bytes live in GCS; Firestore stores URIs/signed URLs and metadata. Pydantic models in `api/models_*.py` define the shapes (`models_core`, `models_projects`, `models_avatar`, `models_infra`, `models_records`).

| Collection | Holds | Lifecycle status field |
|------------|-------|------------------------|
| `_productions` | Project + brief + scenes (script, frame URI, clip URI per scene) | `draft → analyzing → scripted → generating → stitching → completed / failed` |
| `_reframes` | Reframe job: source, options, focal path, outputs | `pending → analyzing → processing → encoding → completed / failed` |
| `_promos` | Promo job: source, analyzed segments, overlays, final | `pending → … → completed / failed` |
| `_adapts` | Adapt job with a **variants[]** array (one per aspect ratio) | per-variant `pending`, plus record-level rollup |
| `_key_moments` | Extracted high-interest clips/timeline | `pending → analyzing → completed / failed` |
| `_thumbnails` | Screenshot analysis + generated collage | `pending → analyzing → completed / failed` |
| `_uploads` | User-uploaded media metadata | — |
| `_avatars`, `_avatar_turns` | Avatar definitions; per-turn render records | turn: `pending → rendering → completed / failed` |
| `_invite_codes` | Access codes + `is_active`, `is_master` | — |
| `_models` | Configurable AI model + region registry | — |
| System resources | Prompt/schema library (versioned, `is_active`) | — |

**Record conventions**
- IDs are prefixed random tokens (`generate_id("res-")`, etc.).
- Every job record carries a `UsageMetrics` block: **facts** (input/output tokens, image count, video-seconds, processing minutes) and **denormalized cost caches** — authoritative cost is always recomputed from facts (see §5).
- The generic CRUD layer (`firestore_service._get/_create/_update/_delete_record`) backs all collections; routers expose them through `routers/_crud.py`.

---

## 4. Request Lifecycles by Feature

### 4.1 Productions (interactive + async)

```
New Project (form)  → POST /productions                (create draft)
"Analyze"           → POST /productions/{id}/analyze    (sync: Gemini brief→scenes)   status=scripted
Storyboard frames   → POST .../scenes/{sid}/frame       (sync: Imagen)                per-scene frame URI
"Generate video"    → POST .../scenes/{sid}/video       (Veo; long)                   status=generating
Stitch              → POST /productions/{id}/stitch      (Transcoder; long)            status=stitching→completed
Poll                → GET  /productions/{id}             (frontend usePolling)
```
Scripting and frame generation are fast enough to run synchronously in the API; Veo rendering and stitching are the heavy steps. The frontend orchestrates the multi-step flow with `useProjectStore` holding form state.

### 4.2 Reframe / Promo / Adapts / Key-moments / Thumbnails (pure async)

All follow the canonical pattern: `POST` creates a `pending` record and returns `{id}`; the worker picks it up; the frontend polls `GET /{id}`. Pipelines differ:

- **Reframe** — download → (diarization + MediaPipe → Gemini focal points → smoothed path → FFmpeg crop/pan) *or* vertical-split → Transcoder stitch.
- **Promo** — Gemini segment analysis → FFmpeg cuts → optional title card (Imagen) + text overlays → codec normalize → Transcoder stitch.
- **Adapts** — per aspect-ratio variant: Imagen generate → write variant URI; roll usage up to the record.
- **Key-moments / Thumbnails** — Gemini video analysis → timeline/screenshots → optional collage.

### 4.3 Live avatar (real-time, WebSocket)

```
Browser  ──WSS /api/v1/avatars/{id}/live?invite_code=…──►  API proxy  ──►  Vertex AI Gemini Live
   ▲  mic → AudioWorklet → 16kHz PCM int16 → realtimeInput.audio
   └─ fragmented MP4 (video+audio) ◄── serverContent.modelTurn.parts
       └─ mp4box demux → WebCodecs VideoDecoder/AudioDecoder → canvas + WebAudio (audio-anchored lip-sync)
```
This is the only path that bypasses the poll model: it needs sub-second bidirectional streaming. The API acts purely as an authenticated proxy so credentials stay server-side.

### 4.4 Chat ("Ask Aanya")

`POST /chat` builds a fresh ADK orchestrator, runs the user turn through orchestrator → specialist, and returns the final text plus an `agent_context` payload (confirmation cards, source pickers). Specialists call API routers **in-process** (ASGI transport) and never execute billable jobs directly — they emit `propose_*` cards the UI confirms.

---

## 5. Pricing & Cost Engine

The design principle: **store facts, derive money.**

```
pre-run:   POST /pricing/estimate ──► pricing_estimator.estimate_cost()
                                       └─ line items + total from pricing_config rates
during:    worker → service returns usage (tokens / images / seconds / minutes)
                                       └─ cost_tracking.* → Firestore Increment(delta)   (race-free)
post-run:  GET /pricing/usage/{feature}/{id}
                                       └─ recompute authoritative cost from stored facts × current rates
```

- **`pricing_config.py`** — the single source of truth: tiered per-token rates (e.g. a threshold at 200K input tokens), per-image, per-video-second, and per-minute (Transcoder, Speech) rates.
- **`cost_tracking.py`** — atomic accumulators (`accumulate_text/image/video_cost_on`) dispatch by feature to the right Firestore update, using `Increment` so concurrent workers can't clobber counters.
- **Cost caches vs. truth** — cost fields on records are denormalized caches; `/pricing/usage` always recomputes from facts, so a rate change never rewrites history and estimates/actuals stay consistent.

---

## 6. Configuration & Regions

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLOUD_PROJECT` | GCP project |
| `GOOGLE_CLOUD_LOCATION` | **Infra** region (Transcoder, Speech) — snapshotted in `deps.py` at import time |
| `GEMINI_REGION` | Region for Gemini/ADK; `main.py` overwrites `GOOGLE_CLOUD_LOCATION` with this for the genai SDK |
| `VEO_REGION` | Veo region (often `us-central1`) |
| `GCS_BUCKET` | Media bucket |
| `OPTIMIZE_PROMPT_MODEL` / `STORYBOARD_MODEL` / `VIDEO_GEN_MODEL` / `GEMINI_AGENT_ORCHESTRATOR` | Model IDs per stage |
| `MASTER_INVITE_CODE` | Master access code |
| `VITE_GUEST_INVITE_CODE` | Baked into the frontend build for auto guest login |

> The region split is a real footgun: the genai/ADK SDK and the infra SDKs read the *same* `GOOGLE_CLOUD_LOCATION` env var but need *different* values. `deps.py` captures the infra region at import before `main.py` mutates the env var for the agent SDK. Preserve this ordering.

---

## 7. Scaling Characteristics

- **API service** — stateless; scales horizontally on Cloud Run by request load. Synchronous AI calls (analyze, frame) are the slowest endpoints; everything heavy is offloaded to the worker.
- **Worker service** — scales horizontally by instance count; each instance polls independently and processes ≤ `MAX_CONCURRENT` jobs/cycle. Throughput ≈ `instances × MAX_CONCURRENT / avg_job_time`. CPU-bound FFmpeg work benefits from more vCPU per instance.
- **Firestore** — read amplification from polling (both the worker poll loop and every frontend poller hit it). At small scale this is fine; at larger scale, increase poll intervals, add composite indexes on `status`, or migrate dispatch to Pub/Sub (§9).
- **GCS** — effectively unbounded; signed-URL generation is cached so it isn't a per-request bottleneck (a prior 30 s page-load regression was fixed by caching credential validity).
- **Live avatars** — each session holds an open WebSocket and a Vertex Live connection; concurrency is bounded by Vertex Live quota and is currently master-only.

---

## 8. Failure Handling & Resilience

- **Job failure** — any exception in `process()` → `mark_failed(record, message)`; the error surfaces to the frontend via the polled record. Temp files are cleaned by `TempFileManager`.
- **Worker crash mid-job** — records left in an in-flight status are **reclaimed to `pending`** on the next worker startup (explicitly implemented for avatar turns), so a crash doesn't permanently strand a job.
- **Retry** — the CRUD client exposes a `retry(id)` action that resets a failed job to `pending` for re-processing.
- **Long media** — diarization auto-chunks audio > ~20 min with cross-boundary merging; reframe chunks keypoints and runs FFmpeg workers in parallel; large videos won't exceed single-call limits.
- **Cost safety** — atomic `Increment` means partial/retried runs accumulate correctly rather than double-counting via read-modify-write.
- **Auth fallthrough** — invalid/expired invite codes 401 the API and trigger frontend logout; bot User-Agents 403 before reaching routers.

---

## 9. Known Trade-offs & Future Work

| Trade-off chosen | Cost | When to revisit |
|------------------|------|-----------------|
| **Firestore polling** as the queue | Dispatch latency (≤ poll interval) and read amplification | Move to **Pub/Sub** (push to worker) if job volume or fan-out grows, or latency matters |
| **Poll-and-process** without transactional claim | Small race window for duplicate pickup with many workers | Add compare-and-set `pending → processing` claim, or a lease/heartbeat, before scaling workers wide |
| **Synchronous scripting/frames** in the API | Those endpoints are the slowest API calls | Push to the worker if Gemini/Imagen latency hurts request budgets |
| **Global singletons** in `deps.py` | Implicit coupling; both services share wiring | Fine at current scale; formalize with a DI container if the service set grows |
| **Single unified worker** for all job types | One slow job type can starve others within an instance | Split into per-type worker deployments, or add per-processor concurrency budgets |
| **MASTER_INVITE_CODE** + Firestore codes | Simple, but not user identity / SSO | Introduce real auth (OIDC) if multi-tenant or audit needs arise |
| **In-process agent tools** | Agent shares the API process's resources | Acceptable; isolate if agent load competes with request serving |

---

## 10. Sequence Diagram — Canonical Async Job (Reframe)

```
 Browser            API service           Firestore           Worker             GCS / GCP AI
   │  POST /reframe     │                     │                  │                     │
   │───────────────────►│  create pending     │                  │                     │
   │                    │────────────────────►│                  │                     │
   │  {id, pending}     │                     │                  │                     │
   │◄───────────────────│                     │                  │                     │
   │                    │                     │   poll pending   │                     │
   │                    │                     │◄─────────────────│                     │
   │                    │                     │   record         │                     │
   │                    │                     │─────────────────►│  download source    │
   │                    │                     │                  │────────────────────►│
   │                    │                     │  status=analyzing│  diarize+detect     │
   │                    │                     │◄─────────────────│  Gemini focal pts   │
   │ GET /reframe/{id}  │   read              │                  │  FFmpeg crop/pan    │
   │───────────────────►│────────────────────►│  status=encoding │  Transcoder stitch  │
   │ {analyzing/…}      │◄────────────────────│◄─────────────────│  upload final ─────►│
   │◄───────────────────│                     │  status=completed│                     │
   │ GET … {completed}  │                     │◄─────────────────│                     │
   │◄───────────────────│  + signed output URL│                  │                     │
```

---

## 11. Glossary

- **Production** — an AI-generated video project (concept → script → storyboard → clips → stitched final).
- **Reframe / Orientation** — re-aspect an existing video (e.g. landscape → portrait) via smart crop/pan or vertical split.
- **Adapt** — generate the same image content in multiple aspect ratios for different platforms.
- **Promo** — a short highlight video cut from a longer source.
- **Key moments** — high-interest segments extracted from a video.
- **Turn** — one user↔avatar exchange (a rendered short avatar clip in v1; live-streamed in v2).
- **Master** — privileged user (full mutate + labs features); guests are read-mostly.
- **Facts vs. cost** — usage counters are facts; money is always derived from facts × current rates.
