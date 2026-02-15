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
SERVICE_NAME=${SERVICE_NAME:-veo-production-suite}
ARTIFACT_REPO=${ARTIFACT_REPO:-superexam-repo}
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${SERVICE_NAME}"

# Model Configs
OPTIMIZE_PROMPT_MODEL=${OPTIMIZE_PROMPT_MODEL:-gemini-3-pro-preview}
STORYBOARD_MODEL=${STORYBOARD_MODEL:-gemini-3-pro-image-preview}
VIDEO_GEN_MODEL=${VIDEO_GEN_MODEL:-veo-3.1-generate-001}

echo "🧪 Running Local Pre-flight Checks..."

# --- 1. Frontend Verification ---
echo "🎨 Verifying Frontend Build..."
cd frontend
if [ -f "package-lock.json" ]; then
    npm ci
else
    npm install
fi
npm run build
cd ..
echo "✅ Frontend build successful."

# --- 2. Backend Verification ---
echo "⚙️ Verifying Backend Startup..."
python3 -m venv .deploy_venv
source .deploy_venv/bin/activate
pip install -q -r api/requirements.txt

# Export env vars for local startup check
export GOOGLE_CLOUD_PROJECT=$PROJECT_ID
export GCS_BUCKET=$GCS_BUCKET
export GEMINI_REGION=$GEMINI_REGION
export FIRESTORE_COLLECTION=${FIRESTORE_COLLECTION:-veogen_projects}
export OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL
export STORYBOARD_MODEL=$STORYBOARD_MODEL
export VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL
export PORT=8081

echo "   Starting API locally on port $PORT..."
python api/main.py > /dev/null 2>&1 &
API_PID=$!

sleep 5

if kill -0 $API_PID 2>/dev/null; then
    echo "✅ API started successfully."
    kill $API_PID
else
    echo "❌ API failed to start locally."
    deactivate
    rm -rf .deploy_venv
    exit 1
fi

deactivate
rm -rf .deploy_venv
echo "✨ Local checks passed. Proceeding to Cloud Deployment..."

echo "🚀 Starting deployment for $SERVICE_NAME..."

# 1. Build and Push with Cloud Build
echo "📦 Building and Pushing with Cloud Build..."
gcloud builds submit --tag $IMAGE_NAME --project $PROJECT_ID .

# 2. Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --project $PROJECT_ID \
  --image $IMAGE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --cpu 8 \
  --memory 16Gi \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,GEMINI_REGION=$GEMINI_REGION,FIRESTORE_COLLECTION=$FIRESTORE_COLLECTION,OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL,STORYBOARD_MODEL=$STORYBOARD_MODEL,VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL" \
  --port 8080

echo "✅ Deployment complete!"
