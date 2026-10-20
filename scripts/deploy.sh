#!/bin/bash
set -e

# Find project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/.."
cd "$PROJECT_ROOT"

# Optional target: which service(s) to build + deploy.
#   ./scripts/deploy.sh             → all four (default)
#   ./scripts/deploy.sh api         → API + Next.js SSR only
#   ./scripts/deploy.sh agents      → Dedicated ADK Agents microservice only
#   ./scripts/deploy.sh productions → Dedicated StoryGraph Productions microservice only
#   ./scripts/deploy.sh worker      → Background worker only
TARGET="${1:-all}"
if [[ "$TARGET" != "all" && "$TARGET" != "api" && "$TARGET" != "worker" && "$TARGET" != "agents" && "$TARGET" != "productions" ]]; then
    echo "Usage: $0 [all|api|agents|productions|worker]  (default: all)"
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
PROJECT_ID=${GOOGLE_CLOUD_PROJECT:-aug18-25-3}
REGION=${GOOGLE_CLOUD_LOCATION:-asia-south1}
GEMINI_REGION=${GEMINI_REGION:-global}
VEO_REGION=${VEO_REGION:-global}
GCS_BUCKET=${GCS_BUCKET:-aug18-25-3-veo-generators-media}
SERVICE_NAME=${SERVICE_NAME:-veo-generators}
WORKER_SERVICE_NAME="${SERVICE_NAME}-worker"
AGENTS_SERVICE_NAME="${SERVICE_NAME}-agents"
PRODUCTIONS_SERVICE_NAME="${SERVICE_NAME}-productions"
ARTIFACT_REPO=${ARTIFACT_REPO:-superexam-repo}
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${SERVICE_NAME}"
WORKER_IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${WORKER_SERVICE_NAME}"
AGENTS_IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${AGENTS_SERVICE_NAME}"
PRODUCTIONS_IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${PRODUCTIONS_SERVICE_NAME}"

# Model Configs
OPTIMIZE_PROMPT_MODEL=${OPTIMIZE_PROMPT_MODEL:-gemini-3.8-flash}
STORYBOARD_MODEL=${STORYBOARD_MODEL:-gemini-nano-banana-2.1}
ADAPTS_MODEL=${ADAPTS_MODEL:-gemini-nano-banana-2.1}
VIDEO_GEN_MODEL=${VIDEO_GEN_MODEL:-gemini-omni-1.1-flash-preview}
GEMINI_AGENT_ORCHESTRATOR=${GEMINI_AGENT_ORCHESTRATOR:-gemini-3.5-flash-lite}
GEMINI_AGENT_FINOPS_MODEL=${GEMINI_AGENT_FINOPS_MODEL:-gemini-3.5-flash-lite}
GEMINI_AGENT_SPECIALIST_MODEL=${GEMINI_AGENT_SPECIALIST_MODEL:-gemini-3.8-flash}
GEMINI_AGENT_CREATIVE_MODEL=${GEMINI_AGENT_CREATIVE_MODEL:-gemini-3.8-flash}
AVATAR_VIDEO_MODEL=${AVATAR_VIDEO_MODEL:-gemini-omni-1.1-flash-preview}
AVATAR_LIVE_MODEL=${AVATAR_LIVE_MODEL:-gemini-3.8-live}
AVATAR_LIVE_LOCATION=${AVATAR_LIVE_LOCATION:-us}
AVATAR_LIVE_PROJECT=${AVATAR_LIVE_PROJECT:-$PROJECT_ID}

# Dubbing (Gemini Live Translate). Developer-API only — this is the one feature
# that authenticates with an API key rather than the runtime service account.
DUBBING_LIVE_MODEL=${DUBBING_LIVE_MODEL:-gemini-3.5-live-translate-preview}
DUBBING_LIVE_SURFACE=${DUBBING_LIVE_SURFACE:-developer}
DUBBING_LIVE_LOCATION=${DUBBING_LIVE_LOCATION:-global}
# NOTE: the target-language list is deliberately NOT an env var. The codes are
# the Live Translate model's contract; they live in models_records.DUB_LANGUAGES.
DUBBING_WINDOW_SEC=${DUBBING_WINDOW_SEC:-600}
DUBBING_PACE=${DUBBING_PACE:-1.0}
DUBBING_SILENCE_STOP_SEC=${DUBBING_SILENCE_STOP_SEC:-4.0}
DUBBING_MAX_SOURCE_MINUTES=${DUBBING_MAX_SOURCE_MINUTES:-30}
DUBBING_MAX_LANGUAGES=${DUBBING_MAX_LANGUAGES:-4}

# gcloud splits --set-env-vars on commas by default, so any value containing one
# is parsed as extra malformed pairs and the deploy dies at argument parsing.
# The "^DELIM^" prefix switches the separator for the whole string; "@" is safe
# for every value we pass (ids, regions, model names, API keys, invite codes).
# Kept even though no current value contains a comma — it costs nothing and the
# failure it prevents is an opaque one.
ENV_DELIM='^@^'

# The worker cannot dub without this key. Fail here rather than shipping a
# revision whose dubbing jobs all fail at the first Live session.
# TODO: move to Secret Manager (--set-secrets) once the deploying identity has
# secretmanager access; it is passed as a plain env var on a private
# (--no-allow-unauthenticated) service in the meantime.
if [[ "$TARGET" == "all" || "$TARGET" == "worker" ]] && [ -z "${GEMINI_API_KEY}" ]; then
    echo "❌ GEMINI_API_KEY is not set in .env — required for the dubbing worker."
    exit 1
fi

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

# Resolve existing API URL for Agents Service tool calls
VEOGEN_API_ORIGIN=${VEOGEN_API_ORIGIN:-$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)' 2>/dev/null || echo "https://veo-generators-1086704919590.asia-south1.run.app")}

# ── Dedicated ADK Agents Service ─────────────────────────────
if [[ "$TARGET" == "all" || "$TARGET" == "agents" ]]; then
  echo "📦 Building ADK Agents image..."
  docker build -f Dockerfile.agents -t $AGENTS_IMAGE_NAME .

  echo "📤 Pushing ADK Agents image..."
  docker push $AGENTS_IMAGE_NAME

  echo "🚀 Deploying ADK Agents ($AGENTS_SERVICE_NAME) to Cloud Run..."
  gcloud run deploy $AGENTS_SERVICE_NAME \
    --project $PROJECT_ID \
    --image $AGENTS_IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --no-invoker-iam-check \
    --execution-environment gen2 \
    --cpu 2 \
    --memory 4Gi \
    --no-cpu-throttling \
    --timeout 3600 \
    --min-instances 1 \
    --max-instances 1 \
    --set-env-vars "${ENV_DELIM}GOOGLE_CLOUD_PROJECT=$PROJECT_ID@GOOGLE_CLOUD_LOCATION=$REGION@GEMINI_REGION=$GEMINI_REGION@VEOGEN_API_ORIGIN=$VEOGEN_API_ORIGIN@MASTER_INVITE_CODE=$MASTER_INVITE_CODE@GEMINI_AGENT_ORCHESTRATOR=$GEMINI_AGENT_ORCHESTRATOR@GEMINI_AGENT_FINOPS_MODEL=$GEMINI_AGENT_FINOPS_MODEL@GEMINI_AGENT_SPECIALIST_MODEL=$GEMINI_AGENT_SPECIALIST_MODEL@GEMINI_AGENT_CREATIVE_MODEL=$GEMINI_AGENT_CREATIVE_MODEL" \
    --port 8080

  prune_revisions "$AGENTS_SERVICE_NAME"
  echo "✅ ADK Agents deployment complete!"
fi

# Resolve Agents Service URL so Next.js Server Actions route /api/v1/chat to it
AGENTS_SERVICE_ORIGIN=${AGENTS_SERVICE_ORIGIN:-$(gcloud run services describe "$AGENTS_SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)' 2>/dev/null || echo "")}

# ── Dedicated StoryGraph Productions Service ─────────────────
if [[ "$TARGET" == "all" || "$TARGET" == "productions" ]]; then
  echo "📦 Building StoryGraph Productions image..."
  docker build -f Dockerfile.productions -t $PRODUCTIONS_IMAGE_NAME .

  echo "📤 Pushing StoryGraph Productions image..."
  docker push $PRODUCTIONS_IMAGE_NAME

  echo "🚀 Deploying StoryGraph Productions ($PRODUCTIONS_SERVICE_NAME) to Cloud Run..."
  gcloud run deploy $PRODUCTIONS_SERVICE_NAME \
    --project $PROJECT_ID \
    --image $PRODUCTIONS_IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --no-invoker-iam-check \
    --execution-environment gen2 \
    --cpu 4 \
    --memory 8Gi \
    --no-cpu-throttling \
    --timeout 3600 \
    --min-instances 1 \
    --max-instances 1 \
    --set-env-vars "${ENV_DELIM}GOOGLE_CLOUD_PROJECT=$PROJECT_ID@GOOGLE_CLOUD_LOCATION=$REGION@GCS_BUCKET=$GCS_BUCKET@GEMINI_REGION=$GEMINI_REGION@VEO_REGION=$VEO_REGION@STORYBOARD_MODEL=$STORYBOARD_MODEL@VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL@GEMINI_AGENT_SPECIALIST_MODEL=$GEMINI_AGENT_SPECIALIST_MODEL@GEMINI_AGENT_CREATIVE_MODEL=$GEMINI_AGENT_CREATIVE_MODEL@MASTER_INVITE_CODE=$MASTER_INVITE_CODE" \
    --port 8080

  prune_revisions "$PRODUCTIONS_SERVICE_NAME"
  echo "✅ StoryGraph Productions deployment complete!"
fi

# Resolve Productions Service URL so Next.js Server Actions route /api/v1/productions/* to it
PRODUCTIONS_SERVICE_ORIGIN=${PRODUCTIONS_SERVICE_ORIGIN:-$(gcloud run services describe "$PRODUCTIONS_SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)' 2>/dev/null || echo "")}

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
    --no-invoker-iam-check \
    --execution-environment gen2 \
    --cpu 2 \
    --memory 4Gi \
    --no-cpu-throttling \
    --timeout 3600 \
    --min-instances 1 \
    --max-instances 1 \
    --set-env-vars "${ENV_DELIM}GOOGLE_CLOUD_PROJECT=$PROJECT_ID@GOOGLE_CLOUD_LOCATION=$REGION@GCS_BUCKET=$GCS_BUCKET@GEMINI_REGION=$GEMINI_REGION@VEO_REGION=$VEO_REGION@SERVICE_NAME=$SERVICE_NAME@AGENTS_SERVICE_ORIGIN=$AGENTS_SERVICE_ORIGIN@PRODUCTIONS_SERVICE_ORIGIN=$PRODUCTIONS_SERVICE_ORIGIN@OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL@STORYBOARD_MODEL=$STORYBOARD_MODEL@ADAPTS_MODEL=$ADAPTS_MODEL@VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL@GEMINI_AGENT_ORCHESTRATOR=$GEMINI_AGENT_ORCHESTRATOR@GEMINI_AGENT_FINOPS_MODEL=$GEMINI_AGENT_FINOPS_MODEL@GEMINI_AGENT_SPECIALIST_MODEL=$GEMINI_AGENT_SPECIALIST_MODEL@GEMINI_AGENT_CREATIVE_MODEL=$GEMINI_AGENT_CREATIVE_MODEL@MASTER_INVITE_CODE=$MASTER_INVITE_CODE@AVATAR_LIVE_MODEL=$AVATAR_LIVE_MODEL@AVATAR_LIVE_LOCATION=$AVATAR_LIVE_LOCATION@AVATAR_LIVE_PROJECT=$AVATAR_LIVE_PROJECT@AVATAR_LIVE_PRESET_NAME=${AVATAR_LIVE_PRESET_NAME:-Kira}@DUBBING_MAX_LANGUAGES=$DUBBING_MAX_LANGUAGES@DUBBING_MAX_SOURCE_MINUTES=$DUBBING_MAX_SOURCE_MINUTES" \
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
    --set-env-vars "${ENV_DELIM}GOOGLE_CLOUD_PROJECT=$PROJECT_ID@GCS_BUCKET=$GCS_BUCKET@GEMINI_REGION=$GEMINI_REGION@VEO_REGION=$VEO_REGION@GOOGLE_CLOUD_LOCATION=$REGION@SERVICE_NAME=$SERVICE_NAME@OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL@VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL@AVATAR_VIDEO_MODEL=$AVATAR_VIDEO_MODEL@WORKER_POLL_INTERVAL=5@WORKER_MAX_CONCURRENT=1@GEMINI_API_KEY=$GEMINI_API_KEY@DUBBING_LIVE_MODEL=$DUBBING_LIVE_MODEL@DUBBING_LIVE_SURFACE=$DUBBING_LIVE_SURFACE@DUBBING_LIVE_LOCATION=$DUBBING_LIVE_LOCATION@DUBBING_WINDOW_SEC=$DUBBING_WINDOW_SEC@DUBBING_PACE=$DUBBING_PACE@DUBBING_SILENCE_STOP_SEC=$DUBBING_SILENCE_STOP_SEC@DUBBING_MAX_SOURCE_MINUTES=$DUBBING_MAX_SOURCE_MINUTES@DUBBING_MAX_LANGUAGES=$DUBBING_MAX_LANGUAGES"

  prune_revisions "$WORKER_SERVICE_NAME"
  echo "✅ Worker deployment complete!"
fi

echo "🎉 Deploy ($TARGET) complete!"
