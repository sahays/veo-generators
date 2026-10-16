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
if [ ! -d "node_modules" ]; then
    if [ -f "package-lock.json" ]; then
        npm ci --registry=https://registry.npmjs.org/
    else
        npm install --registry=https://registry.npmjs.org/
    fi
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
# Persist the venv at api/venv (gitignored) so lint AND tests run against the
# full dependency set, and repeat runs are fast.
if [ ! -d "api/venv" ]; then
    echo "📦 Creating virtual environment at api/venv..."
    python3 -m venv api/venv || uv venv api/venv --default-index https://pypi.org/simple --seed || { echo "❌ Failed to create virtual environment."; exit 1; }
    source api/venv/bin/activate
    echo "📦 Installing backend dependencies (ruff, pytest, requirements)..."
    pip install -q --index-url https://pypi.org/simple --upgrade pip
    pip install -q --index-url https://pypi.org/simple ruff pytest -r api/requirements.txt
else
    source api/venv/bin/activate
fi

echo "   Running Ruff linting..."
if ruff check --isolated --select E4,E7,E9,F --exclude api/venv api workers; then
    echo "   ✅ Ruff lint passed."
else
    echo "   ❌ Ruff lint failed. Please fix issues."
    exit 1
fi

echo "   Running Ruff format..."
ruff format --isolated --exclude api/venv api workers
echo "   ✅ Ruff format applied."

# Ensure system shared libraries that some Python deps load at import time
# (opencv/mediapipe need libGL + libglib2) are present; install if missing.
ensure_system_lib() {
    local lib="$1" dnf_pkg="$2" apt_pkg="$3"
    if ldconfig -p 2>/dev/null | grep -q "$lib"; then
        return 0
    fi
    echo "   ⚠️  System library $lib is missing — attempting install..."
    local mgr_cmd
    if command -v dnf >/dev/null 2>&1; then
        mgr_cmd="dnf install -y -q $dnf_pkg"
    elif command -v yum >/dev/null 2>&1; then
        mgr_cmd="yum install -y -q $dnf_pkg"
    elif command -v apt-get >/dev/null 2>&1; then
        mgr_cmd="apt-get install -y -qq $apt_pkg"
    else
        echo "   ❌ No supported package manager (dnf/yum/apt-get) to install $lib." >&2
        exit 1
    fi
    if ! sudo -n true 2>/dev/null; then
        echo "   ❌ $lib missing and passwordless sudo unavailable. Install manually: sudo $mgr_cmd" >&2
        exit 1
    fi
    [ "${mgr_cmd%% *}" = "apt-get" ] && sudo apt-get update -qq
    if sudo $mgr_cmd; then
        echo "   ✅ Installed $lib."
    else
        echo "   ❌ Failed to install $lib (sudo $mgr_cmd)." >&2
        exit 1
    fi
}

echo "   Checking system libraries..."
ensure_system_lib "libGL.so.1" "mesa-libGL" "libgl1"
ensure_system_lib "libgthread-2.0.so.0" "glib2" "libglib2.0-0"
echo "   ✅ System libraries present."

echo "   Running backend tests (pytest)..."
if (cd api && python3 -m pytest tests/ -q); then
    echo "   ✅ Backend tests passed."
else
    echo "   ❌ Backend tests failed. Please fix before deploying."
    exit 1
fi

echo "   Running AST static checker (duplicate code & tier-breakers)..."
if python3 scripts/check_architecture.py; then
    echo "   ✅ AST static checker passed."
else
    echo "   ❌ AST static checker failed."
    exit 1
fi

echo "   Running UI component usage checker..."
if python3 scripts/check_components.py; then
    echo "   ✅ UI component usage checker passed."
else
    echo "   ❌ UI component usage checker failed."
    exit 1
fi

echo "✨ All pre-deployment checks passed!"
