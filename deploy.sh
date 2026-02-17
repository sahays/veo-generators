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
ARTIFACT_REPO=${ARTIFACT_REPO:-superexam-repo}
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${SERVICE_NAME}"

# Model Configs
OPTIMIZE_PROMPT_MODEL=${OPTIMIZE_PROMPT_MODEL:-gemini-3-pro-preview}
STORYBOARD_MODEL=${STORYBOARD_MODEL:-gemini-3-pro-image-preview}
VIDEO_GEN_MODEL=${VIDEO_GEN_MODEL:-veo-3.1-generate-001}

# Execute comprehensive pre-deployment checks
./pre-deploy.sh

echo "🚀 Starting deployment for $SERVICE_NAME..."

# Ensure Docker is authenticated with Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# 1. Build locally and push to Artifact Registry
echo "📦 Building locally..."
docker build -t $IMAGE_NAME .

echo "📤 Pushing to Artifact Registry..."
docker push $IMAGE_NAME

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
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,GEMINI_REGION=$GEMINI_REGION,VEO_REGION=$VEO_REGION,SERVICE_NAME=$SERVICE_NAME,OPTIMIZE_PROMPT_MODEL=$OPTIMIZE_PROMPT_MODEL,STORYBOARD_MODEL=$STORYBOARD_MODEL,VIDEO_GEN_MODEL=$VIDEO_GEN_MODEL" \
  --port 8080

echo "✅ Deployment complete!"
