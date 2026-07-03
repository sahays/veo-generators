#!/bin/bash
set -e

# Find project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT"

# Optional target: which service(s) to build + deploy.
#   ./scripts/deploy.sh          → both (default)
#   ./scripts/deploy.sh api      → API only (frontend bundles into this image)
#   ./scripts/deploy.sh worker   → worker only
TARGET="${1:-all}"
if [[ "$TARGET" != "all" && "$TARGET" != "api" && "$TARGET" != "worker" ]]; then
    echo "Usage: $0 [all|api|worker]  (default: all)"
    exit 1
fi
echo "🎯 Deploy target: $TARGET"

# Load environment variables from .env file
if [ -f .env ]; then
    echo "📄 Loading configuration from .env..."
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ .env file not found. Please create it from .env.example."
    exit 1
fi

# Configuration with defaults
PROJECT_ID=${GOOGLE_CLOUD_PROJECT}
REGION=${GOOGLE_CLOUD_LOCATION:-asia-south1}
GEMINI_REGION=${GEMINI_REGION:-us-central1}
GCS_BUCKET=${GCS_BUCKET}
SERVICE_NAME=${SERVICE_NAME:-veo-generators}
WORKER_SERVICE_NAME="${SERVICE_NAME}-worker"
ARTIFACT_REPO=${ARTIFACT_REPO:-superexam-repo}
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${SERVICE_NAME}"
WORKER_IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${WORKER_SERVICE_NAME}"

# Model Configs
OPTIMIZE_PROMPT_MODEL=${OPTIMIZE_PROMPT_MODEL:-gemini-3-pro-preview}
STORYBOARD_MODEL=${STORYBOARD_MODEL:-gemini-3.1-flash-image-preview}
VIDEO_GEN_MODEL=${VIDEO_GEN_MODEL:-veo-3.1-generate-001}

# Note: run ./scripts/pre-deploy.sh first for the full gate (frontend build,
# ruff lint/format, system-lib check, backend tests). Deploy runs the backend
# tests below on its own so it stays safe even if invoked directly, without
# re-running the whole pre-deploy suite twice.

# Run backend tests (abort on failure)
echo "🧪 Running Backend Tests..."
if [ -d "api/venv" ]; then
    echo "📦 Using existing virtual environment at api/venv..."
    source api/venv/bin/activate
else
    echo "📦 Creating virtual environment at .test_venv..."
    python3 -m venv .test_venv || { echo "❌ Failed to create virtual environment. Ensure python3-venv is installed."; exit 1; }
    source .test_venv/bin/activate
    pip install -q pytest httpx -r api/requirements.txt
fi

cd api
if python3 -m pytest tests/ -v --no-header 2>&1 | grep -q "no tests ran"; then
    echo "⚠️  No tests found. Skipping."
elif python3 -m pytest tests/ -v; then
    echo "✅ All tests passed."
else
    echo "❌ Tests failed. Aborting deployment."
    cd "$PROJECT_ROOT"
    if [ -d ".test_venv" ]; then
        deactivate && rm -rf .test_venv
    fi
    exit 1
fi
cd "$PROJECT_ROOT"
if [ -d ".test_venv" ]; then
    deactivate && rm -rf .test_venv
fi

echo "🚀 Starting deployment for $SERVICE_NAME..."

# Keep only the latest 5 revisions of a Cloud Run service; delete the rest.
# Cloud Run never garbage-collects old revisions, so they pile up. The active
# (traffic-serving) revision is always the newest, so it's safely within the
# kept window. Non-fatal: deletion failures (e.g. a revision still serving
# traffic) are ignored so a cleanup hiccup never aborts a successful deploy.
prune_revisions() {
    local service="$1"
    echo "🧹 Pruning old revisions for $service (keeping latest 5)..."
    local stale
    stale=$(gcloud run revisions list \
        --service "$service" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --sort-by='~metadata.creationTimestamp' \
        --format='value(metadata.name)' 2>/dev/null | tail -n +6)
    if [ -z "$stale" ]; then
        echo "   Nothing to prune."
        return 0
    fi
    while IFS= read -r rev; do
        [ -z "$rev" ] && continue
        echo "   Deleting revision $rev"
        gcloud run revisions delete "$rev" \
            --project "$PROJECT_ID" \
            --region "$REGION" \
            --quiet 2>/dev/null || echo "   ⚠️  Could not delete $rev (skipping)"
    done <<< "$stale"
}

# Ensure Docker is authenticated with Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# ── API Service ──────────────────────────────────────────────
if [[ "$TARGET" == "all" || "$TARGET" == "api" ]]; then
  echo "📦 Building API image..."
  docker build \
    --build-arg VITE_GUEST_INVITE_CODE="${VITE_GUEST_INVITE_CODE}" \
    -t $IMAGE_NAME .

  echo "📤 Pushing API image..."
  docker push $IMAGE_NAME

  echo "🚀 Deploying API to Cloud Run..."
  gcloud run deploy $SERVICE_NAME \
    --project $PROJECT_ID \
    --image $IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --cpu 8 \
    --memory 16Gi \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,GEMINI_REGION=$GEMINI_REGION,VEO_REGION=$VEO_REGION,SERVICE_NAME=$SERVICE_NAME,OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL,STORYBOARD_MODEL=$STORYBOARD_MODEL,VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL,MASTER_INVITE_CODE=$MASTER_INVITE_CODE,AVATAR_LIVE_LOCATION=${AVATAR_LIVE_LOCATION:-us-central1},AVATAR_LIVE_PROJECT=${AVATAR_LIVE_PROJECT:-ffeldhaus-avatar-demo},AVATAR_LIVE_PRESET_NAME=${AVATAR_LIVE_PRESET_NAME:-Kira}" \
    --port 8080

  prune_revisions "$SERVICE_NAME"
  echo "✅ API deployment complete!"
fi

# ── Worker Service ───────────────────────────────────────────
if [[ "$TARGET" == "all" || "$TARGET" == "worker" ]]; then
  echo "📦 Building Worker image..."
  docker build -f Dockerfile.worker -t $WORKER_IMAGE_NAME .

  echo "📤 Pushing Worker image..."
  docker push $WORKER_IMAGE_NAME

  echo "🚀 Deploying Worker to Cloud Run..."
  gcloud run deploy $WORKER_SERVICE_NAME \
    --project $PROJECT_ID \
    --image $WORKER_IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --no-allow-unauthenticated \
    --execution-environment gen2 \
    --cpu 8 \
    --memory 16Gi \
    --no-cpu-throttling \
    --timeout 3600 \
    --min-instances 1 \
    --max-instances 1 \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,GEMINI_REGION=$GEMINI_REGION,GOOGLE_CLOUD_LOCATION=$REGION,SERVICE_NAME=$SERVICE_NAME,OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL,WORKER_POLL_INTERVAL=5,WORKER_MAX_CONCURRENT=1"

  prune_revisions "$WORKER_SERVICE_NAME"
  echo "✅ Worker deployment complete!"
fi

echo "🎉 Deploy ($TARGET) complete!"
