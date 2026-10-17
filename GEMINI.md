# Veo Generators - Developer Notes

This file summarizes key architecture, performance optimizations, dependencies, and scripts of the Veo Generators platform.

## AI Agent Best Practices
Use subagents and parallelize tasks whenever possible. Use the right Gemini model for the task. Tasks that require judgement and reasoning gets the frontier with caliberated effort switch e.g. Argon 4 High/Medium/Low, others can use faster and cheaper Flash models e.g. Flash 3.8 Low/Medium. Share only required information between the agents by developing a typed input and output data exchange contract.

## Coding Instructions (Must Follow Every Time)
- No brute force. Always find the best algorithm and data structure to implement
- DRY, SOLID, and Principles of Clean Code
- OWASP top 10
- Keep files small (400 statements per file max; comments not counted)
- Keep functions small (25-30 statements per function max; comments not counted)
- Always Typed Python and Typsescript
- Respect and maintain code tiers and never break them e.g. frontend never calls DB directly
- Do not dump in a flat file structure. Use folders to organize code
- Write scripts to enforce these coding instructions and use them with pre-deploy step script (details below)
- Semantic Logging: Logs should be able to answer Who, Where, What, When, Why, and How
- Tests: No vanity tests. No tests for the sake of coverage. Tests should be written for the complex logic and edge cases. Good tests fail and catch issues and regressions when code under tests change. 

## Architecture & Tech Stack
- **Frontend**: Next.js 15 (`output: 'standalone'` SSR), React 18, TypeScript, TailwindCSS, Radix UI / Shadcn-style primitives (`frontend/src/components/ui/`), Framer Motion, Zustand, and Zod (under `frontend/`).
- **Server-to-Server API Layer**: All frontend REST API calls execute server-to-server via Next.js Server Actions (`frontend/src/lib/api/serverAction.ts`) to FastAPI over internal loopback (`127.0.0.1:8000`), while WebSocket upgrades (`/api/v1/avatars/*/live`) are tunneled at the TCP socket level via `frontend/start-standalone.cjs`.
- **Backend API**: Python, FastAPI, Uvicorn, GCP Firestore & GCS (under `api/`).
- **Worker Service**: Background workers processing heavy tasks asynchronously (under `workers/`).
- **Orchestration**: Powered by `google-adk` (Google Agent Development Kit).

## Performance Optimizations
- **Signed GCS URLs**: Synchronous, sequential token refreshes in `api/storage_service.py` previously caused a ~30-second latency on page loads. We implemented credential validation caching (`if not self.credentials.valid`) on the singletons, reducing URL-signing times from hundreds of milliseconds to $< 1\text{ ms}$ per URL.

## Codebase Index (O(1) Discovery)
- **[CODEBASE_INDEX.md](file:///usr/local/google/home/sanjeetsahay/projects/veogen/CODEBASE_INDEX.md)** & **[CODEBASE_INDEX.json](file:///usr/local/google/home/sanjeetsahay/projects/veogen/CODEBASE_INDEX.json)**: Pre-computed architectural index of the entire repository (`api/`, `workers/`, `agents_service/`, `productions_service/`, `scripts/`, and `frontend/src/`). Contains the directory tree, domain packages, and every file's path, architectural tier, non-comment line count, and exported classes/functions/endpoints. Read `CODEBASE_INDEX.md` or `CODEBASE_INDEX.json` first in agent sessions for $O(1)$ symbol and module retrieval instead of performing broad filesystem searches.

## Core Development Scripts
All scripts are located in the [scripts/](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts) directory. They are location-independent (can be executed from any folder) and use the local virtual environment (`api/venv`) if available:

* **[scripts/unit-tests.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/unit-tests.sh)**: Automatically runs the full backend test suite (`pytest`) in the current virtual environment or a fallback container.
* **[scripts/pre-deploy.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/pre-deploy.sh)**: Performs TypeScript compilation and Next.js SSR build checks on the frontend, runs `ruff` linting/formatting and `pytest` on the backend, runs all static checkers (`check_architecture.py`, `check_components.py`, and `check_coding_standards.py`), and refreshes `CODEBASE_INDEX.json` & `CODEBASE_INDEX.md`.
* **[scripts/generate_codebase_index.py](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/generate_codebase_index.py)**: Fast AST/regex codebase index generator that scans all backend services, scripts, and frontend sources to emit `CODEBASE_INDEX.json` and `CODEBASE_INDEX.md`.
* **[scripts/check_architecture.py](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/check_architecture.py)**: AST static checker enforcing zero duplicate code blocks and zero 4-tier architecture hierarchy violations across Python and TypeScript (backed by `scripts/checkers/arch_tiers.py` and `scripts/checkers/ast_clones.py`).
* **[scripts/check_components.py](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/check_components.py)**: Static UI checker enforcing zero raw HTML controls (`<button>`, `<a>`, `<input>`, `<textarea>`, `<select>`), zero flat `bg-accent` button overrides, zero deprecated `steel-*` classes, and zero browser `fetch()` calls outside `frontend/src/lib/api/serverAction.ts`.
* **[scripts/check_coding_standards.py](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/check_coding_standards.py)**: AST and regex static checker enforcing No-Brute-Force complexity bounds, DRY/SOLID principles, OWASP Top 10 security rules, file/function statement limits (max 400 per file, 30 per function), strict Python/TypeScript typing, and tier isolation.
* **[scripts/deploy-local.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/deploy-local.sh)**: Automates the setup of the local environment, backend venv, frontend node packages, and prepares the Next.js standalone SSR bundle.
* **[scripts/deploy.sh](file:///usr/local/google/home/sanjeetsahay/projects/veogen/scripts/deploy.sh)**: Builds the Docker containers, pushes them to Artifact Registry, and deploys both the API and Worker instances to Google Cloud Run.

## Dependency Resolution
- We fixed an import-level incompatibility between this project's code and standard `google-adk` package structure:
  - `InMemorySessionService` is now imported from `google.adk.sessions` (instead of `google.adk.runners`).
  - `types` is imported from `google.genai`.
  - Under this configuration, the full test suite (184 unit tests) executes and passes cleanly in under 4 seconds.
