#!/bin/bash
set -e

# Find project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT"

echo "🔍 Running Pre-Deployment Checks..."

# --- Frontend Checks ---
echo "🎨 Checking Frontend..."
cd frontend
if [ -f "package-lock.json" ]; then
    npm ci
else
    npm install
fi

echo "   Running TypeScript checks and build..."
# This runs tsc (type check) and vite build
if npm run build; then
    echo "✅ Frontend build passed."
else
    echo "❌ Frontend build failed."
    exit 1
fi
cd "$PROJECT_ROOT"

# --- Backend Checks ---
echo "⚙️ Checking Backend..."
# Use existing api/venv if available, otherwise try to create one
if [ -d "api/venv" ]; then
    echo "📦 Using existing virtual environment at api/venv..."
    source api/venv/bin/activate
else
    echo "📦 Creating virtual environment at .lint_venv..."
    python3 -m venv .lint_venv || { echo "❌ Failed to create virtual environment. Ensure python3-venv is installed."; exit 1; }
    source .lint_venv/bin/activate
    pip install -q ruff -r api/requirements.txt
fi

echo "   Running Ruff linting..."
if ruff check api workers; then
    echo "   ✅ Ruff lint passed."
else
    echo "   ❌ Ruff lint failed. Please fix issues."
    if [ -d ".lint_venv" ]; then
        deactivate && rm -rf .lint_venv
    fi
    exit 1
fi

echo "   Running Ruff format..."
ruff format api workers
echo "   ✅ Ruff format applied."

if [ -d ".lint_venv" ]; then
    deactivate && rm -rf .lint_venv
fi
echo "✨ All pre-deployment checks passed!"
