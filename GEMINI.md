# Veo Generators - Developer Notes

This file summarizes key architecture, performance optimizations, dependencies, and scripts of the Veo Generators platform.

## Architecture & Tech Stack
- **Frontend**: Next.js 15 (`output: 'standalone'` SSR), React 18, TypeScript, TailwindCSS, Radix UI / Shadcn-style primitives (`frontend/src/components/ui/`), Framer Motion, Zustand, and Zod (under `frontend/`).
- **Server-to-Server API Layer**: All frontend REST API calls execute server-to-server via Next.js Server Actions (`frontend/src/lib/api/serverAction.ts`) to FastAPI over internal loopback (`127.0.0.1:8000`), while WebSocket upgrades (`/api/v1/avatars/*/live`) are tunneled at the TCP socket level via `frontend/start-standalone.cjs`.
- **Backend API**: Python, FastAPI, Uvicorn, GCP Firestore & GCS (under `api/`).
- **Worker Service**: Background workers processing heavy tasks asynchronously (under `workers/`).
- **Orchestration**: Powered by `google-adk` (Google Agent Development Kit).

## Performance Optimizations
- **Signed GCS URLs**: Synchronous, sequential token refreshes in `api/storage_service.py` previously caused a ~30-second latency on page loads. We implemented credential validation caching (`if not self.credentials.valid`) on the singletons, reducing URL-signing times from hundreds of milliseconds to $< 1\text{ ms}$ per URL.

## Core Development Scripts
All scripts are located in the [scripts/](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts) directory. They are location-independent (can be executed from any folder) and use the local virtual environment (`api/venv`) if available:

* **[scripts/unit-tests.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/unit-tests.sh)**: Automatically runs the full backend test suite (`pytest`) in the current virtual environment or a fallback container.
* **[scripts/pre-deploy.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/pre-deploy.sh)**: Performs TypeScript compilation and Next.js SSR build checks on the frontend, runs `ruff` linting/formatting and `pytest` on the backend, and runs both static checkers (`check_architecture.py` and `check_components.py`).
* **[scripts/check_architecture.py](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/check_architecture.py)**: AST static checker enforcing zero duplicate code blocks and zero 4-tier architecture hierarchy violations across Python and TypeScript.
* **[scripts/check_components.py](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/check_components.py)**: Static UI checker enforcing zero raw HTML controls (`<button>`, `<a>`, `<input>`, `<textarea>`, `<select>`), zero flat `bg-accent` button overrides, zero deprecated `steel-*` classes, and zero browser `fetch()` calls outside `frontend/src/lib/api/serverAction.ts`.
* **[scripts/deploy-local.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/deploy-local.sh)**: Automates the setup of the local environment, backend venv, frontend node packages, and prepares the Next.js standalone SSR bundle.
* **[scripts/deploy.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/deploy.sh)**: Builds the Docker containers, pushes them to Artifact Registry, and deploys both the API and Worker instances to Google Cloud Run.

## Dependency Resolution
- We fixed an import-level incompatibility between this project's code and standard `google-adk` package structure:
  - `InMemorySessionService` is now imported from `google.adk.sessions` (instead of `google.adk.runners`).
  - `types` is imported from `google.genai`.
  - Under this configuration, the full test suite (184 unit tests) executes and passes cleanly in under 4 seconds.
