# VeoGen — Architecture Overview

> AI-powered video production platform built on Google **Veo**, **Gemini**, **Imagen**, and supporting GCP media services. VeoGen turns a one-line concept into a scripted, storyboarded, rendered, and stitched video — and offers a suite of derivative tools (reframing, promos, aspect-ratio adapts, thumbnails, key-moments, and live avatars).

This document describes the system at a high level: its components, how they communicate, and the principal data and control flows. For deeper detail on the job model, data schema, pricing, and failure handling, see [system-design.md](./system-design.md). For the end-user feature walkthrough, see [README.md](./README.md).

---

## 1. System at a Glance

VeoGen is a **three-tier, two-service** application deployed on Google Cloud Run:

| Tier | Technology | Responsibility |
|------|------------|----------------|
| **Frontend** | React 18 + TypeScript + Vite + Tailwind | SPA UI; talks to the API over REST; polls for async job status; opens a WebSocket for live avatars |
| **API service** | Python 3.12 + FastAPI + Uvicorn | Synchronous request handling, validation, auth, agent chat, and job *enqueue* (write a `pending` record to Firestore) |
| **Worker service** | Python 3.12 (same image base, no web server) | Polls Firestore for `pending` jobs and executes long-running media pipelines (FFmpeg, Veo, Transcoder, Speech) |
| **State / storage** | Firestore (Native mode) + Google Cloud Storage | Firestore holds all metadata & job state; GCS holds media bytes (uploads, frames, clips, finals) |

```
                         ┌──────────────────────────────────────────────┐
                         │                Browser (SPA)                 │
                         │  React • Zustand • React Query • WebCodecs    │
                         └───────────────┬───────────────┬──────────────┘
                                REST /api/v1             │ WSS (live avatar)
                                         │               │
              ┌──────────────────────────▼───────────────▼───────────────────┐
              │                     API SERVICE (Cloud Run)                   │
              │  FastAPI app  •  middleware (bot guard, invite-code auth)     │
              │  routers/  →  services (gemini/video/storage/...)             │
              │  agents/  (Google ADK orchestrator + specialists)             │
              └───────┬───────────────────┬───────────────────┬──────────────┘
                      │ write pending      │ read/write        │ proxy
                      │ + read status      │ media bytes       │ Gemini Live
                      ▼                    ▼                   ▼
              ┌──────────────┐     ┌──────────────┐    ┌────────────────────┐
              │  Firestore   │     │     GCS      │    │  Vertex AI Live API │
              │ (job state)  │     │ (media blobs)│    └────────────────────┘
              └──────┬───────┘     └──────┬───────┘
                     │ poll pending       │ read/write
                     ▼                    ▼
              ┌─────────────────────────────────────────────────────────────┐
              │                   WORKER SERVICE (Cloud Run)                  │
              │  unified_worker  →  JobProcessor (reframe/promo/adapts/avatar)│
              │  FFmpeg • MediaPipe • Gemini • Veo • Transcoder • Speech V2   │
              └─────────────────────────────────────────────────────────────┘
                     │
                     ▼  (all heavy GCP/AI calls)
        Vertex AI (Gemini, Imagen, Veo) • Transcoder API • Speech-to-Text V2 (Chirp 3)
```

**The defining architectural choice:** the API never blocks on a long render. It writes a `pending` record to Firestore and returns immediately. A **separate worker service polls Firestore** and runs the pipeline. The frontend **polls the API** for status. This decouples request latency from render time and lets the two services scale independently.

---

## 2. Components

### 2.1 Frontend (`frontend/`)

A single-page React application. Key choices:

- **Routing** — React Router v7, client-side. `App.tsx` gates the whole app behind an invite code (`InviteCodeGate`) and splits routes by role (master vs. guest).
- **State** — Zustand stores (`store/`): `useAuthStore` (invite code + master flag, persisted), `useProjectStore` (multi-step production form), `useChatStore` (Aanya chat history), `useLayoutStore` (sidebar/theme). React Query handles server cache.
- **API layer** — `lib/api/` is layered: `_http.ts` (fetch wrapper that injects the `X-Invite-Code` header and handles 401/429), `_crud.ts` (a generic REST client factory), and one module per feature. `lib/api.ts` is the aggregating facade.
- **Async UX** — `hooks/usePolling.ts` polls a job record every ~5 s while its status is non-terminal; `hooks/jobStatus.ts` standardizes status labels/colors. No WebSocket for ordinary jobs.
- **Live avatars** — the one real-time path: `AudioCapture` (mic → 16 kHz PCM via AudioWorklet) → backend WS proxy → Gemini Live; the response (fragmented MP4 multiplexing video+audio) is demuxed with **mp4box.js** and rendered through **WebCodecs** (`VideoCanvasSink`) with manual audio-anchored lip-sync.

### 2.2 API service (`api/`)

FastAPI app (`main.py`) composed of:

- **Middleware stack** — a bot-protection middleware (blocks `curl`/`requests`/etc. by User-Agent, allowlisting the internal `veoagent`) and an **invite-code middleware** that validates the `X-Invite-Code` header against the master code + Firestore, sets `request.state.is_master`, and enforces that mutating methods (and `/api/v1/avatars/*` entirely) are master-only.
- **Routers** (`routers/`) — one module per feature: `productions`, `scenes`, `render`, `uploads`, `key_moments`, `thumbnails`, `reframe`, `promo`, `adapts`, `system`, `diagnostics`, `auth`, `chat`, `models`, `pricing`, `avatars`, `avatars_live`. They share a generic CRUD helper (`_crud.py`).
- **Services** (`*_service.py`) — the integration layer wrapping each external dependency (see §3).
- **Agents** (`agents/`) — a Google ADK orchestrator + specialists for the conversational "Ask Aanya" co-pilot (see §4).
- **Dependency wiring** (`deps.py`) — services are module-level singletons created once in the FastAPI `startup` hook and shared by both routers and (via import) the worker.
- **Static hosting** — in production the built frontend is bundled into `static/` and served by the same FastAPI app (catch-all route for client-side routing).

### 2.3 Worker service (`workers/`)

A headless Python process (`unified_worker.py`) with no web server. It imports the same `api/` service singletons and runs a poll loop:

- A registry of `JobProcessor` subclasses (`reframe`, `promo`, `adapts`, `avatar`), each defining `get_pending_records()` and `process(record)`.
- Every `WORKER_POLL_INTERVAL` (~5 s) the dispatcher asks each processor for `pending` records and runs them, bounded by `MAX_CONCURRENT`.
- `base_processor.py` provides shared machinery: atomic status/progress updates, failure marking, a sync↔async bridge (`_run_async`) since processors are synchronous but services are async, and a `TempFileManager` for scratch files.
- On startup it **reclaims orphans** (e.g. avatar turns left mid-render by a crashed worker) by resetting them to `pending`.

---

## 3. Service Integration Layer (`api/*_service.py`)

Each service encapsulates one external dependency, keeping GCP/AI SDK details out of routers and processors.

| Service | Wraps | Responsibility |
|---------|-------|----------------|
| `gemini_service.py` | Vertex AI — Gemini & Imagen | Brief→scene analysis, storyboard frames, aspect-ratio adapt images, video analysis for promos/key-moments. Multi-region client cache. |
| `video_service.py` | Vertex AI — **Veo** | Scene clip generation (text+image→video, 4/6/8 s) with enriched prompts and per-project deterministic seeds. |
| `avatar_service.py` | Vertex AI — Gemini Flash Lite | Generates short (<25-word) avatar replies shaped by persona/tone; feeds the lip-sync render. |
| `reframe_service.py` | FFmpeg (local) | Smart crop/pan reframing along a focal path; vertical-split mode; chunked + parallel processing. |
| `diarization_service.py` | Speech-to-Text V2 (Chirp 3) | Batch transcription with speaker diarization; auto-chunks long audio with boundary merging. |
| `transcoder_service.py` | Cloud Video Transcoder API | Stitches clips per a GCS manifest into a single 720p H.264/AAC output. |
| `storage_service.py` | Google Cloud Storage | Upload/download blobs; cached-credential **signed URL** generation (48 h, auto-refresh). |
| `firestore_service.py` | Firestore | Document CRUD for every record type via a shared generic pattern. |
| `cost_tracking.py` | Firestore (`Increment`) | Race-free accumulation of per-job token/image/video/minute usage. |
| `pricing_*.py` | — | Single source of truth for rates; pre-run estimates and post-run cost recomputation. |

> **Region nuance:** `main.py` overrides `GOOGLE_CLOUD_LOCATION` to the Gemini region for the genai/ADK SDK, so `deps.py` snapshots the *real* infra region at import time for Transcoder/Speech, which must run in their own region.

---

## 4. Conversational Agent ("Ask Aanya")

A master-only chat co-pilot built on **Google ADK** (`api/agents/`):

- **Orchestrator** (`factory.py`) — a router LLM agent that delegates by intent and itself answers pricing questions. Sub-agents:
  - **Director** — productions, scripts, system-prompt library.
  - **Editor** — reframing, thumbnails, key moments.
  - **Marketer** — promos, multi-platform adapts.
- **Tools** (`agents/tools/`) call the FastAPI routers **in-process** via an HTTPX `ASGITransport` client — no network hop, but goes through the same middleware/validation (injecting the invite code).
- **Propose-then-confirm** — specialists don't execute jobs directly; they return *confirmation cards* (`propose_*` tools) that the UI renders, so the user confirms before any billable run.
- **Isolation** — each chat request builds a fresh orchestrator and resets a `contextvars`-scoped context, preventing cross-request leakage under concurrency. The chat endpoint drives it with an ADK `Runner` + `InMemorySessionService`.

---

## 5. Data & Control Flow — the canonical async job

Using **reframe** as the archetype (promo, adapts, avatar follow the same shape):

```
1. POST /api/v1/reframe                       (API service)
   └─ validate → create ReframeRecord(status="pending") in Firestore
   └─ return {id, status} immediately            ◄── request ends fast

2. Worker poll loop (≤5s later)                (Worker service)
   └─ ReframeProcessor.get_pending_records() → finds the record
   └─ process(record):
        • download source from GCS, ffprobe
        • [AI path] diarization (Chirp 3) + MediaPipe detection
                    → Gemini focal-point analysis → smoothed camera path
                    → FFmpeg crop/pan  (or vertical-split path)
        • Transcoder stitch → final MP4 to GCS
        • update_status(...,"completed",100) + accumulate cost
   └─ on error: mark_failed(record, message)

3. GET /api/v1/reframe/{id}  (polled by SPA)   (API service)
   └─ returns current status/progress/output URLs
```

Productions are slightly different (interactive, multi-step): scripting and storyboard frames are generated **synchronously** through the API (fast Gemini/Imagen calls), while per-scene Veo rendering and final stitching are the long-running steps. Status moves through `draft → analyzing → scripted → generating → stitching → completed`.

**Cost model:** pricing is computed from *facts*. Usage counters (tokens, images, video-seconds, processing minutes) are written via Firestore `Increment` during a run; the authoritative cost is (re)computed on demand by `/pricing` from those facts against the current rate table in `pricing_config.py`. A pre-run `/pricing/estimate` gives the user a line-item forecast.

---

## 6. Security & Access Control

- **Invite-code gate** — every request (except health/docs/static) requires a valid `X-Invite-Code`, validated against a master code and a Firestore code registry with an `is_active` flag.
- **Role enforcement** — only master users may mutate state; the entire `/api/v1/avatars/*` surface is master-only (Vertex Live allowlist-pending). Read-only POSTs (`/auth/validate`, `/pricing/estimate`) are explicitly allowlisted for guests.
- **Bot protection** — User-Agent screening blocks common scripting clients while allowlisting the internal agent.
- **Credential handling** — the browser never sees GCP credentials; media is served via short-lived signed URLs, and the live-avatar WebSocket is proxied server-side (invite code passed as a query param since WS upgrades can't carry custom headers).

---

## 7. Deployment

Two container images, both deployed to Cloud Run:

- **`Dockerfile`** (API) — multi-stage: build the React app (`node:24`), then a `python:3.12-slim` image with FFmpeg that installs the API deps and bundles the frontend `dist/` into `static/`. Runs `python main.py`.
- **`Dockerfile.worker`** — `python:3.12-slim` + FFmpeg, copies both `api/` and `workers/`, runs `python workers/unified_worker.py`.

`scripts/deploy.sh` runs pre-deploy checks (TypeScript compile, Ruff lint) and the pytest suite, builds & pushes both images to Artifact Registry, and deploys both Cloud Run services. Configuration (project, regions, bucket, models, master invite code) is supplied via environment variables.

**Required GCP services:** Cloud Run, Artifact Registry, Firestore, Cloud Storage, Vertex AI (`aiplatform`), Transcoder, and Speech-to-Text V2.

---

## 8. Key Architectural Decisions (and why)

1. **Firestore polling instead of Pub/Sub** — trades a few seconds of dispatch latency for operational simplicity; no broker, no subscriptions, trivially observable job state. Status *is* the queue.
2. **Separate API and worker services** — request latency is decoupled from render time; the CPU/IO-heavy worker scales independently from the lightweight API.
3. **Shared service singletons** — both services import the same `deps.py` wiring, avoiding duplicated SDK setup and keeping behavior identical across tiers.
4. **In-process agent tools (ASGI transport)** — agents reuse the real API surface (and its auth/validation) without a network hop.
5. **Propose-then-confirm agents** — no billable AI job runs without explicit user confirmation.
6. **Cost as a derived value** — store facts, compute money; rate changes never corrupt historical truth, and estimates/actuals share one rate table.
7. **WebCodecs + mp4box for live avatars** — direct frame/sample decode gives precise, audio-anchored lip-sync that MediaSource couldn't reliably deliver for the fragmented-MP4 stream.

---

## 9. Where to Look in the Code

| Concern | Entry point |
|---------|-------------|
| App composition, middleware, auth | `api/main.py` |
| Service wiring / singletons | `api/deps.py` |
| Feature endpoints | `api/routers/*.py` |
| External integrations | `api/*_service.py` |
| Conversational agent | `api/agents/factory.py`, `api/agents/specialists/*` |
| Async job model | `workers/unified_worker.py`, `workers/base_processor.py`, `workers/*_processor.py` |
| Pricing / cost | `api/pricing_config.py`, `api/pricing_estimator.py`, `api/cost_tracking.py` |
| Data models | `api/models_*.py` |
| Frontend shell & routing | `frontend/src/App.tsx`, `frontend/src/main.tsx` |
| Frontend API + polling | `frontend/src/lib/api/*`, `frontend/src/hooks/usePolling.ts` |
| Live avatar pipeline | `frontend/src/components/avatar/live/*` |
