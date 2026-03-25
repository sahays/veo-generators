#!/bin/bash
set -e

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
cd ..

# --- Backend Checks ---
echo "⚙️ Checking Backend..."
# Create a temporary venv for linting and testing tools
python3 -m venv .lint_venv
source .lint_venv/bin/activate
pip install -q ruff -r api/requirements.txt

echo "   Running Ruff linting..."
if ruff check api workers; then
    echo "   ✅ Ruff lint passed."
else
    echo "   ❌ Ruff lint failed. Please fix issues."
    deactivate && rm -rf .lint_venv
    exit 1
fi

echo "   Running Ruff format..."
ruff format api workers
echo "   ✅ Ruff format applied."

deactivate
rm -rf .lint_venv
echo "✨ All pre-deployment checks passed!"
