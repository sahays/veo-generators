#!/bin/bash
set -e

# Find project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT"

echo "🚀 Setting up local environment for Veo Generators..."

# 1. Setup Backend
echo "⚙️ Setting up Backend..."
if [ -d "api/venv" ]; then
    echo "📦 Existing virtual environment at api/venv found. Updating..."
    source api/venv/bin/activate
else
    echo "📦 Creating virtual environment at api/venv..."
    python3 -m venv api/venv || { echo "❌ Failed to create virtual environment. Ensure python3-venv is installed."; exit 1; }
    source api/venv/bin/activate
fi
pip install --upgrade pip
pip install -r api/requirements.txt
# Add httpx and others if not already in requirements (they should be from previous steps)
pip install httpx python-dotenv google-adk google-cloud-aiplatform

# 2. Setup Frontend
echo "🎨 Setting up Frontend..."
cd frontend
if [ -f "package-lock.json" ]; then
    npm ci
else
    npm install
fi

echo "🏗️ Building Frontend..."
npm run build
cd "$PROJECT_ROOT"

# 3. Prepare static directory for API
echo "📁 Syncing frontend build to API static folder..."
rm -rf api/static
mkdir -p api/static
cp -r frontend/dist/* api/static/

echo ""
echo "✨ Local setup complete!"
echo ""
echo "To run the application:"
echo "1. Ensure your .env file is configured (copy .env.example if needed)"
echo "2. Backend API: source api/venv/bin/activate && cd api && uvicorn main:app --reload --port 8080"
echo "3. Worker: source api/venv/bin/activate && export PYTHONPATH=\$PYTHONPATH:\$(pwd)/api && python workers/unified_worker.py"
echo "4. Access the app at: http://localhost:8080"
