# Veo Generators - Developer Notes

This file summarizes key architecture, performance optimizations, dependencies, and scripts of the Veo Generators platform.

## Architecture & Tech Stack
- **Frontend**: React, TypeScript, Vite, TailwindCSS (under `frontend/`).
- **Backend API**: Python, FastAPI, Uvicorn, GCP Firestore & GCS (under `api/`).
- **Worker Service**: Background workers processing heavy tasks asynchronously (under `workers/`).
- **Orchestration**: Powered by `google-adk` (Google Agent Development Kit).

## Performance Optimizations
- **Signed GCS URLs**: Synchronous, sequential token refreshes in `api/storage_service.py` previously caused a ~30-second latency on page loads. We implemented credential validation caching (`if not self.credentials.valid`) on the singletons, reducing URL-signing times from hundreds of milliseconds to $< 1\text{ ms}$ per URL.

## Core Development Scripts
All scripts are located in the [scripts/](file:///usr/local/google/home/sanjeetsahay/projects/veo-generators/scripts) directory. They are location-independent (can be executed from any folder) and use the local virtual environment (`api/venv`) if available:

* **[scripts/unit-tests.sh](file:///usr/local/google/home/sanjeetsahay/projects/veo-generators/scripts/unit-tests.sh)**: Automatically runs the full backend test suite (`pytest`) in the current virtual environment or a fallback container.
* **[scripts/pre-deploy.sh](file:///usr/local/google/home/sanjeetsahay/projects/veo-generators/scripts/pre-deploy.sh)**: Performs TypeScript compilation checks on the frontend and runs `ruff` linting and formatting on the backend.
* **[scripts/deploy-local.sh](file:///usr/local/google/home/sanjeetsahay/projects/veo-generators/scripts/deploy-local.sh)**: Automates the setup of the local environment, backend venv, frontend node packages, and copies distribution assets.
* **[scripts/deploy.sh](file:///usr/local/google/home/sanjeetsahay/projects/veo-generators/scripts/deploy.sh)**: Builds the Docker containers, pushes them to Artifact Registry, and deploys both the API and Worker instances to Google Cloud Run.

## Dependency Resolution
- We fixed an import-level incompatibility between this project's code and standard `google-adk` package structure:
  - `InMemorySessionService` is now imported from `google.adk.sessions` (instead of `google.adk.runners`).
  - `types` is imported from `google.genai`.
  - Under this configuration, the full test suite (184 unit tests) executes and passes cleanly in under 4 seconds.
