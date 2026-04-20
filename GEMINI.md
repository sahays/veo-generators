# Veo Generators Project Overview

Veo Generators is a full-stack, AI-driven application for automated video production using Google's generative models (Gemini, Imagen, Veo). It orchestrates a pipeline that transforms creative concepts into structured scripts, storyboards, and finally, high-quality video clips stitched into a single MP4.

## 🏗 Architecture & Tech Stack

The project follows a decoupled architecture with a FastAPI backend and a React frontend, utilizing Google Cloud services for infrastructure and AI capabilities.

- **Frontend:**
  - **Framework:** React 18 with TypeScript and Vite.
  - **State Management:** Zustand.
  - **Data Fetching:** TanStack Query (React Query).
  - **Styling:** Tailwind CSS with Framer Motion for animations.
  - **Icons:** Lucide React.
  - **Forms:** React Hook Form with Zod validation.

- **Backend (API):**
  - **Framework:** FastAPI (Python 3.12+).
  - **Data Modeling:** Pydantic.
  - **Authentication:** Custom invite-code system (Master/Non-Master roles).
  - **Middlewares:** Bot protection and Invite Code validation.
  - **Services:** Decoupled service layer for Firestore, GCS, Vertex AI, and Video Transcoder.

- **Worker Service:**
  - **Purpose:** A standalone Python service that polls Firestore for pending background jobs.
  - **Processors:** `ReframeProcessor`, `PromoProcessor`, `AdaptsProcessor`.
  - **Concurrency:** Configurable via environment variables.

- **Google Cloud Integration:**
  - **Database:** Firestore (Native mode).
  - **Storage:** Google Cloud Storage (GCS) for media assets.
  - **AI Models:** Vertex AI (Gemini for scripts, Imagen for storyboards, Veo for video).
  - **Video Processing:** Cloud Video Transcoder API for stitching clips.
  - **Compute:** Google Cloud Run (Containerized API and Worker).

## 🛠 Building and Running

### Prerequisites
- Node.js (18+)
- Python (3.12+)
- Docker
- Google Cloud CLI (gcloud)

### Backend (Local Development)
1. Navigate to the `api/` directory.
2. Create and activate a virtual environment.
3. Install dependencies: `pip install -r requirements.txt`.
4. Set up `.env.dev` (refer to `.env.example`).
5. Start the API: `uvicorn main:app --reload --port 8080`.

### Frontend (Local Development)
1. Navigate to the `frontend/` directory.
2. Install dependencies: `npm install`.
3. Start the dev server: `npm run dev`.

### Worker (Local Development)
1. Navigate to the `workers/` directory.
2. Ensure the `api/` directory is in your `PYTHONPATH`.
3. Run the worker: `python unified_worker.py`.

### Deployment
Deployment is automated via the `deploy.sh` script, which:
1. Runs `pre-deploy.sh` (TS check, Linting).
2. Runs backend `pytest` tests.
3. Builds and pushes Docker images for both API and Worker.
4. Deploys to Google Cloud Run.

```bash
chmod +x deploy.sh pre-deploy.sh
./deploy.sh
```

## 🧪 Testing

- **Backend:** Uses `pytest`. Run tests with `cd api && pytest tests/`.
- **Frontend E2E:** Uses `Playwright`.
  - `npm run e2e`: Run full E2E tests.
  - `npm run e2e:screenshots`: Run screenshot generation tests.

## 📏 Development Conventions

- **Project Structure:**
  - `api/routers/`: API endpoints grouped by feature.
  - `api/schemas/`: JSON/Pydantic schemas for data validation.
  - `api/*.py`: Service-specific logic (e.g., `firestore_service.py`).
  - `frontend/src/components/`: UI components (Common, Pages, Shared).
  - `frontend/src/store/`: Zustand stores.
  - `workers/`: Background job processors.
- **Linting:** Python code is linted using Ruff (configured in `pre-deploy.sh`).
- **Auth:** All API requests (except health checks) require an `X-Invite-Code` header.
- **CI/CD:** Pre-deployment checks in `pre-deploy.sh` ensure type safety and code quality before shipping.
