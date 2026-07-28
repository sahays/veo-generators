# Veo Generators — Self-Hosting & Feature Guide

A full-stack, AI-driven application for automated video production using Google's generative models (Gemini, Imagen, Veo). This project acts as an orchestration layer: define a creative concept, and it is automatically broken down into a script, storyboarded, rendered into clips, and stitched together — then reframed, localized, trimmed, and thumbnailed for whatever platform you are publishing to.

---

## 📚 Documentation

| Document | What's in it |
|---|---|
| [docs/architecture.md](docs/architecture.md) | High-level component map — services, data flow, control flow. **Start here.** |
| [docs/system-design.md](docs/system-design.md) | The *how*: async job model, Firestore schema, per-feature request lifecycles, pricing engine, scaling and failure behavior |
| [docs/README.md](docs/README.md) | End-user walkthrough of every screen, with screenshots |
| [docs/orientation.md](docs/orientation.md) | Reframe pipeline architecture — why each stage exists |
| [docs/reframing-v2.md](docs/reframing-v2.md) | Current reframe design: perception, semantics, global rung DP, pan paths |
| [docs/reframing-v1.md](docs/reframing-v1.md) | The first reframe design, kept for context on what changed |
| [docs/reframing-eval.md](docs/reframing-eval.md) | How reframe quality is evaluated |
| [docs/dubbing.md](docs/dubbing.md) | Multi-language dubbing via Gemini Live Translate, with sequence diagrams |
| [docs/ask-aanya-tools.md](docs/ask-aanya-tools.md) | The ADK agent tool surface behind the "Ask Aanya" co-pilot |
| [docs/conversational-ui-plan.md](docs/conversational-ui-plan.md) | Design notes for the conversational UI |
| [CLAUDE.md](CLAUDE.md) | Repo conventions: deploy sequence, test commands, project layout |

---

## ✨ Features

### Production pipeline

**AI scriptwriting** — turns a one-sentence prompt into a structured, multi-scene script with visual descriptions, narration, and estimated timestamps. From the dashboard, click **New Project**, enter your concept, and pick a length and orientation.

**Automated storyboarding** — generates a static frame per scene from its visual description, so you can pre-visualize before spending compute on video. Auto-generate all frames or refine scenes individually.

**Scene-by-scene video generation** — renders short clips per scene with Veo, using the storyboard frame plus the scene description as a combined image-and-text prompt.

**Final stitching** — merges the scene clips into one MP4 via the Google Cloud Video Transcoder API.

### Derivative media tools

Each of these takes an existing video — an uploaded file or a finished production — and runs an asynchronous worker job over it.

**Orientations (reframe)** — converts 16:9 to 9:16 or 3:4 without manual re-editing. Combines face/person detection, Gemini scene understanding, and a smoothed pan path so the right subject stays in frame. See [orientation.md](docs/orientation.md) and [reframing-v2.md](docs/reframing-v2.md).

**Dubbing** — generates dubbed versions across twelve targets — English, Spanish, Portuguese (Brazil and Portugal), German, French, Hindi, Bengali, Tamil, Telugu, Kannada, and Malayalam — using `gemini-3.5-live-translate-preview`, a speech-to-speech simultaneous interpreter that carries the speaker's intonation across languages. Each language returns an MP4, a translated transcript, and an SRT. See [dubbing.md](docs/dubbing.md).

**Promos** — Gemini picks the strongest segments, FFmpeg cuts them, and the result is assembled into a short promo with an optional generated title card.

**Key moments** — analyzes a video and returns timestamped highlight segments with descriptions and relevance scores, plus a summary.

**Thumbnails** — captures key frames and composites them into a collage thumbnail.

**Adapts** — regenerates a still into multiple aspect ratios with Imagen, one variant per ratio.

### Conversational

**Live avatar** — a real-time bidirectional WebSocket conversation with a Gemini Live avatar. The only path in the system that bypasses the polling model; the API acts purely as an authenticated proxy so credentials stay server-side.

**Ask Aanya** — a master-only co-pilot built on the Google Agent Development Kit. Specialist agents call the API in-process and propose actions as confirmation cards rather than launching billable jobs directly. See [ask-aanya-tools.md](docs/ask-aanya-tools.md).

### Operations

**Cost and token tracking** — the design principle is *store facts, derive money*. Workers record what was actually consumed (tokens, images, seconds, minutes); cost is recomputed from those facts against current rates, so correcting a rate needs no backfill. Pre-run estimates are available before you spend anything.

**Gated access control** — invite codes with per-code daily quotas, enforced in middleware. Master codes are unlimited. Rate-limited routes are exactly the POST endpoints that consume Gemini/Veo credits; reads, auth, uploads, and deletes never count against quota.

---

## 🏗 Architecture at a glance

```
                    ┌──────────────────────┐
   Browser ────────▶│  API  (Cloud Run)    │──── Firestore ────┐
   React + Vite     │  FastAPI             │                   │
                    │  serves the frontend │──── GCS           │
                    └──────────┬───────────┘                   │
                               │ writes status=pending         │
                               ▼                               │
                    ┌──────────────────────┐                   │
                    │  WORKER (Cloud Run)  │◀──── polls ───────┘
                    │  ffmpeg, OpenCV,     │
                    │  MediaPipe, Veo      │──── Vertex AI / Gemini API
                    └──────────────────────┘
```

Two Cloud Run services. Renders take seconds to minutes — far longer than an HTTP request should block — so the job record's `status` field *is* the queue: the API writes `pending`, the worker polls for it, runs the pipeline, and writes a terminal status. No message broker. The frontend polls `GET /{id}`.

The worker runs `--max-instances 1` with `WORKER_MAX_CONCURRENT=1`. That is a deliberate simplicity trade-off — one job at a time, no distributed coordination — and it is why long-running jobs carry source-length guards. See [system-design.md](docs/system-design.md) for the full reasoning.

---

## 🛠 Self-hosting on Google Cloud Run

### 1. Prerequisites

- A GCP account with an active project
- [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install), installed and authenticated
- Docker
- Node.js 18+ and Python 3.12+ (for the local pre-deploy checks)
- A **Gemini Developer API key** if you want dubbing — that one feature uses a model that is not available on Vertex AI

### 2. Enable required GCP APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  transcoder.googleapis.com \
  speech.googleapis.com
```

`speech.googleapis.com` backs Chirp 3 diarization, which the reframe pipeline uses to work out who is speaking.

### 3. Set up services and infrastructure

**Cloud Storage** — one bucket for uploads, generated frames, and rendered video:

```bash
gcloud storage buckets create gs://YOUR_GCS_BUCKET_NAME --location=YOUR_REGION
```

**Firestore** — initialize a database in **Native mode**. It holds all job records and application state.

**Artifact Registry** — a Docker repository for the two container images:

```bash
gcloud artifacts repositories create superexam-repo \
  --repository-format=docker \
  --location=YOUR_REGION \
  --description="Veo Generators Docker repo"
```

### 4. IAM

Create a dedicated service account with:

- **Cloud Datastore User** (`roles/datastore.user`) — Firestore reads and writes
- **Storage Object Admin** (`roles/storage.objectAdmin`) — GCS uploads
- **Vertex AI User** (`roles/aiplatform.user`) — Gemini, Imagen, and Veo
- **Transcoder Admin** (`roles/transcoder.admin`) — stitching jobs
- **Service Account Token Creator** (`roles/iam.serviceAccountTokenCreator`) — V4 signed URLs via `signBlob`

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SERVICE_ACCOUNT_EMAIL" \
  --role="roles/aiplatform.user"
```

### 5. Environment variables

Copy `.env.example` to `.env` in the repo root and fill it in. The deploy script reads this file and injects the values into both Cloud Run services.

```env
# Google Cloud
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=asia-south1
GEMINI_REGION=global
VEO_REGION=global
GCS_BUCKET=your-bucket-name

# AI models
OPTIMIZE_PROMPT_MODEL=gemini-3-pro-preview
STORYBOARD_MODEL=gemini-3.1-flash-image-preview
ADAPTS_MODEL=gemini-3.1-flash-image-preview
VIDEO_GEN_MODEL=veo-3.1-generate-001
GEMINI_AGENT_ORCHESTRATOR=gemini-3.1-flash-lite-preview

# Dubbing (Gemini Live Translate — Developer API, not Vertex)
# The target-language list is not configurable here — the codes are the model's
# contract, so they live in api/models_records.py (DUB_LANGUAGES).
GEMINI_API_KEY=your-developer-api-key
DUBBING_LIVE_MODEL=gemini-3.5-live-translate-preview
DUBBING_MAX_SOURCE_MINUTES=30
DUBBING_MAX_LANGUAGES=4

# Service
SERVICE_NAME=veo-generators
ARTIFACT_REPO=superexam-repo

# Auth
MASTER_INVITE_CODE=your-master-invite-code
VITE_GUEST_INVITE_CODE=guest
```

`.env.example` carries the full set with inline notes on the tuning knobs (dubbing pacing, session windows, silence detection). `.env` is gitignored — keep it that way.

> **On `GEMINI_API_KEY`:** it is currently passed to the worker as a plain environment variable on a private, `--no-allow-unauthenticated` service. Prefer Secret Manager (`--set-secrets`) in any environment you care about; the deploy script has a note marking where that swap goes.

### 6. Deploy

Scripts live under `scripts/`. Run them in this order:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

./scripts/pre-deploy.sh          # frontend build + tsc, ruff lint/format, system libs, pytest
./scripts/deploy.sh              # tests, docker build + push, deploy both services
```

`deploy.sh` takes an optional target:

```bash
./scripts/deploy.sh all      # default — API and worker
./scripts/deploy.sh api      # API only (the frontend bundles into this image)
./scripts/deploy.sh worker   # worker only
```

Deploy through these scripts rather than hand-written `docker`/`gcloud` commands — they handle image tagging, env-var escaping, and old-revision pruning consistently. `deploy.sh` does not call `pre-deploy.sh` (that would run the checks twice), so run pre-deploy yourself for the full gate.

On success the script prints the Cloud Run URL for your instance.

### Other scripts

| Script | Purpose |
|---|---|
| `scripts/pre-deploy.sh` | Full local gate: frontend build, ruff, system-lib check, backend tests |
| `scripts/deploy.sh [all\|api\|worker]` | Build, push, and deploy to Cloud Run |
| `scripts/git-push.sh` | Push the current branch without writing a token to disk or the remote URL |
| `scripts/deploy-local.sh` | Set up a local dev environment: venv, frontend build, static sync |
| `scripts/fetch-logs.sh` | Fetch Cloud Logging entries via the attached service account |
| `scripts/unit-tests.sh` | Backend tests on their own |

---

## 🧪 Development

```
api/         FastAPI backend
  main.py                entry point, auth + quota + bot-protection middleware
  deps.py                service singletons (firestore, AI, video, storage, transcoder)
  routers/               route handlers
  models.py              Pydantic models
  firestore_service.py   data access layer
  tests/                 pytest suite
workers/     background job processors (one per feature) + the polling loop
frontend/    React + Vite + Tailwind (TypeScript)
scripts/     deploy and maintenance scripts
docs/        architecture and design documents
```

Run the backend tests directly:

```bash
cd api && python3 -m pytest tests/ -v
```

They need a virtualenv with the dependencies installed; `pre-deploy.sh` maintains one at `api/venv` and runs the suite for you.
