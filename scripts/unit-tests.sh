#!/bin/bash
set -e

# Find project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT"

echo "🧪 Running Unit Tests..."

# Use existing api/venv if available, otherwise try to create one
if [ -d "api/venv" ]; then
    echo "📦 Using existing virtual environment at api/venv..."
    source api/venv/bin/activate
else
    echo "📦 Creating virtual environment at .test_venv..."
    python3 -m venv .test_venv || { echo "❌ Failed to create virtual environment. Ensure python3-venv is installed."; exit 1; }
    source .test_venv/bin/activate
    pip install -q pytest -r api/requirements.txt
fi

cd api
python3 -m pytest tests/ -v --tb=short
cd ..

if [ -d ".test_venv" ]; then
    deactivate
    rm -rf .test_venv
fi

echo "✅ All tests completed!"
