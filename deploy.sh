#!/bin/bash
set -e

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

# Execute comprehensive pre-deployment checks
./pre-deploy.sh

# Run backend tests (abort on failure)
echo "🧪 Running Backend Tests..."
python3 -m venv .test_venv
source .test_venv/bin/activate
pip install -q pytest httpx -r api/requirements.txt
cd api
if python3 -m pytest tests/ -v --no-header 2>&1 | grep -q "no tests ran"; then
    echo "⚠️  No tests found. Skipping."
elif python3 -m pytest tests/ -v; then
    echo "✅ All tests passed."
else
    echo "❌ Tests failed. Aborting deployment."
    cd ..
    deactivate && rm -rf .test_venv
    exit 1
fi
cd ..
deactivate
rm -rf .test_venv

echo "🚀 Starting deployment for $SERVICE_NAME..."

# Ensure Docker is authenticated with Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# ── API Service ──────────────────────────────────────────────
echo "📦 Building API image..."
docker build -t $IMAGE_NAME .

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
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,GEMINI_REGION=$GEMINI_REGION,VEO_REGION=$VEO_REGION,SERVICE_NAME=$SERVICE_NAME,OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL,STORYBOARD_MODEL=$STORYBOARD_MODEL,VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL,MASTER_INVITE_CODE=$MASTER_INVITE_CODE" \
  --port 8080

echo "✅ API deployment complete!"

# ── Worker Service ───────────────────────────────────────────
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

echo "✅ Worker deployment complete!"
echo "🎉 All services deployed!"
