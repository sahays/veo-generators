# Veo Generators

## Project Overview

The **Veo Generators** is a full-stack, AI-driven web application designed to automate and streamline the video production process. It acts as an orchestration layer over Google's generative AI models. The application allows users to define a high-level creative concept, which the system automatically breaks down into a structured script, visualizes with storyboard frames, renders into short video clips, and finally stitches together into a cohesive final MP4 video.

### Tech Stack

*   **Frontend:**
    *   **Framework:** React (Vite) with TypeScript as a Single Page Application (SPA).
    *   **Styling:** Tailwind CSS.
    *   **State Management:** Zustand (e.g., `useAuthStore`, `useProjectStore`, `useLayoutStore`).
    *   **Data Fetching & Routing:** TanStack Query (React Query) and React Router.
*   **Backend:**
    *   **Framework:** Python (FastAPI) utilizing dependency injection (`deps.py`) for highly modular service management.
    *   **Database:** Google Cloud Firestore (NoSQL metadata for Projects, Scenes, Statuses).
    *   **Storage:** Google Cloud Storage (GCS) for binary assets (Images, Videos).
    *   **AI Models:**
        *   Text/Scripting: `gemini-3-preview` (Transforms prompts into structured JSON scripts).
        *   Image/Storyboard: `imagen/nano-banana` (Text-to-Image for scene frames).
        *   Video Generation: `veo-3` (Text/Image-to-Video generation).
    *   **Video Processing:** Google Cloud Video Transcoder API (for post-production stitching).
*   **Infrastructure:**
    *   **Containerization:** Docker (Multi-stage build that compiles the React app and serves it alongside the Python API).
    *   **Deployment:** Google Cloud Run.

## Project Structure

*   **`api/`**: The Python backend application.
    *   `main.py`: Entry point for the FastAPI server. Defines endpoints, background tasks, and security middleware (e.g., `InviteCodeMiddleware`).
    *   `deps.py`: Manages service initialization and dependency injection.
    *   `models.py`: Pydantic data models for Projects, Scenes, and API responses.
    *   `ai_service.py`: Core AI logic. Interfaces with Gemini for script generation and Imagen for storyboard frames.
    *   `video_service.py`: Core production service. Integrates with Google Veo to generate video clips.
    *   `transcoder_service.py`: Post-production service. Uses Google Cloud Transcoder API to merge video clips.
    *   `firestore_service.py` & `storage_service.py`: Persistence handlers for DB and GCS.
    *   `routers/`: Domain-specific API endpoints (`/productions`, `/scenes`, `/render`, `/thumbnails`).
*   **`frontend/`**: The React frontend application.
    *   `src/components/ads/`: Workflow-centric UI components (`ProjectForm.tsx`, `RefinePromptView.tsx`, `StoryboardView.tsx`, and cost tracking via `CostBreakdownPill.tsx`).
    *   `src/pages/`: Segregated views (Dashboard, ConfigSettings, Diagnostics, etc.).
    *   `src/store/`: Zustand state stores.
*   **`prompts/`**: Markdown files containing stylistic templates (e.g., Anderson, Kubrick) and prompt engineering experiments.
*   **`schemas/`**: JSON schemas enforcing the structure of AI outputs.
*   **`deploy.sh`**: Shell script for building and deploying the application to Google Cloud Run.

## Key Workflows & Data Flow

The lifecycle of a single video generation goes through the following state machine pipeline:

1.  **Concept Phase (`DRAFT`):**
    *   User submits a creative brief, target length, and orientation via the frontend.
    *   Backend creates a `Project` entry in Firestore.
2.  **Pre-Production Phase (`SCRIPTED`):**
    *   *Data Flow:* Brief $\rightarrow$ `ai_service` (Gemini) $\rightarrow$ Array of `Scene` objects (visuals, narration, timestamps) stored in Firestore.
3.  **Storyboarding Phase:**
    *   *Data Flow:* Scene Visual Description $\rightarrow$ `ai_service` (Imagen) $\rightarrow$ Thumbnail Image (saved to GCS, URL attached to Scene).
4.  **Rendering Phase (`GENERATING`):**
    *   *Data Flow:* Scene + Thumbnail $\rightarrow$ `video_service` (Veo) $\rightarrow$ Scene Video MP4s (saved to GCS).
    *   *Note:* Handled asynchronously as a background task due to generation times.
5.  **Post-Production Phase (`COMPLETED`):**
    *   *Data Flow:* List of Scene Video GCS URIs $\rightarrow$ `transcoder_service` (Google Cloud Transcoder) $\rightarrow$ Final stitched MP4 $\rightarrow$ URL returned to the frontend.

## Infrastructure & Security

*   **Access Control:** The backend utilizes a custom `InviteCodeMiddleware` in `main.py` to gate access and prevent unauthorized consumption of expensive AI generation APIs.
*   **Cost Tracking:** The frontend explicitly tracks token usage and generation costs (via `CostBreakdownPill.tsx`) to provide users visibility into API expenditures.

## Actionable Insights & Architectural Considerations

*   **Async Handling Constraint:** Video generation with models like Veo takes significant time. Consider replacing client-side polling with Webhooks or Server-Sent Events (SSE) to provide the frontend with real-time progress updates without hammering the backend.
*   **Cost Management:** While cost estimation exists on the frontend, implementing hard quota limits at the database layer (Firestore) per invite-code is recommended to prevent runaway infrastructure costs.
*   **Prompt Engineering:** The system heavily relies on `prompts/` markdown files directing the JSON output. Any structural changes to the data requirements in `schemas/` must be carefully synchronized with these markdown prompt instructions to prevent parsing failures.

## Building and Running

### Prerequisites
*   Node.js (v18+)
*   Python (v3.12+)
*   Google Cloud CLI (`gcloud`) configured with a project.
*   Access to Google Cloud services (Firestore, GCS, Vertex AI/GenAI, Video Transcoder).

### Local Development

1.  **Backend:**
    ```bash
    cd api
    # Create and activate virtual environment (recommended)
    python -m venv venv
    source venv/bin/activate
    
    pip install -r requirements.txt
    
    # Set up environment variables (create .env.dev or export them)
    # Required: GOOGLE_APPLICATION_CREDENTIALS, PROJECT_ID, etc.
    
    python main.py
    ```
    The API will run at `http://localhost:8080`.

2.  **Frontend:**
    ```bash
    cd frontend
    npm install
    npm run dev
    ```
    The frontend will run at `http://localhost:5173` (proxies requests to backend).

### Docker Build

To build the unified image (frontend built and served as static files by backend):

```bash
docker build -t veo-generators .
docker run -p 8080:8080 --env-file .env.dev veo-generators
```

### Deployment

The `deploy.sh` script handles deployment to Google Cloud Run:

```bash
./deploy.sh
```

**Deployed Application:** [https://veo-generators-265936284692.asia-south1.run.app](https://veo-generators-265936284692.asia-south1.run.app)

**Note:** Ensure you have permissions to push to GCR/Artifact Registry and deploy to Cloud Run. The script assumes specific project ID and region variables which may need editing.

## Conventions

*   **API Pattern:** RESTful endpoints under `/api/v1/`.
*   **Data Validation:** Pydantic models in backend, Zod schemas in frontend.
*   **State Management:** Zustand for global client state (projects, layout).
*   **Styling:** Tailwind CSS utility classes.
