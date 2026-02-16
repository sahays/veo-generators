# Veo Generators

## Project Overview

The **Veo Generators** is a full-stack web application designed to streamline the creation of AI-generated videos. It leverages Google's **Gemini** models for scriptwriting and storyboard analysis, and **Veo** (and Imagen) models for video and image generation. The application allows users to define a video concept, which is then automatically broken down into scenes, visualized with thumbnails, and rendered into a final stitched video.

### Tech Stack

*   **Frontend:**
    *   **Framework:** React (Vite) with TypeScript
    *   **Styling:** Tailwind CSS
    *   **State Management:** Zustand
    *   **Data Fetching:** TanStack Query (React Query)
    *   **Routing:** React Router
*   **Backend:**
    *   **Framework:** Python (FastAPI)
    *   **Database:** Google Cloud Firestore
    *   **Storage:** Google Cloud Storage (GCS)
    *   **AI Models:**
        *   Text/Scripting: `gemini-3-preview`
        *   Image/Storyboard: `imagen/nano-banana`
        *   Video Generation: `veo-3`
    *   **Video Processing:** Google Cloud Video Transcoder (for stitching)
*   **Infrastructure:**
    *   **Containerization:** Docker (Multi-stage build)
    *   **Deployment:** Google Cloud Run

## Project Structure

*   **`api/`**: The Python backend application.
    *   `main.py`: Entry point for the FastAPI server. Defines endpoints and background tasks.
    *   `models.py`: Pydantic data models for Projects, Scenes, and API responses.
    *   `ai_service.py`: Logic for interacting with Gemini, Imagen, and Veo models.
    *   `firestore_service.py`: CRUD operations for Firestore.
    *   `storage_service.py`: Helper class for Google Cloud Storage operations.
    *   `requirements.txt`: Python dependencies.
*   **`frontend/`**: The React frontend application.
    *   `src/`: Source code.
        *   `components/`: Reusable UI components (ProjectForm, StoryboardView, etc.).
        *   `pages/`: Application views (Dashboard, ConfigSettings).
        *   `store/`: Zustand state stores.
        *   `lib/`: Utilities and API clients.
    *   `vite.config.ts`: Vite configuration.
*   **`prompts/`**: Markdown files containing example prompts and prompt engineering experiments.
*   **`video-outputs/`**: Local directory for storing generated video files (primarily for testing/examples).
*   **`deploy.sh`**: Shell script for building and deploying the application to Google Cloud Run.
*   **`Dockerfile`**: Defines the multi-stage build process for the application.

## Key Workflows

1.  **Project Creation:**
    *   User submits a "Production" request with a `base_concept`, `video_length`, and `orientation`.
    *   Backend creates a `Project` entry in Firestore with status `DRAFT`.
2.  **Analysis & Scripting (`/analyze`):**
    *   The `ai_service` uses Gemini to analyze the concept and break it down into a list of `Scene` objects, each with a `visual_description` and timestamps.
    *   Project status updates to `SCRIPTED`.
3.  **Storyboard Generation:**
    *   User (or auto-process) requests frame generation for specific scenes.
    *   `ai_service` uses Imagen to generate a thumbnail based on the `visual_description`.
4.  **Video Rendering (`/render`):**
    *   Backend initiates a background task (`process_sequential_generation`).
    *   For each scene, `ai_service` calls the Veo model to generate a video clip.
    *   Clips are stored in GCS.
5.  **Stitching:**
    *   Once all scenes are generated, `ai_service` (via Transcoder API or FFMpeg equivalent) stitches the clips into a single `final_video_url`.
    *   Project status updates to `COMPLETED`.

## Building and Running

### Prerequisites
*   Node.js (v18+)
*   Python (v3.12+)
*   Google Cloud CLI (`gcloud`) configured with a project.
*   Access to Google Cloud services (Firestore, GCS, Vertex AI/GenAI).

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
