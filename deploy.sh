#!/bin/bash

# Configuration
PROJECT_ID="search-and-reco"
REGION="asia-south1"
SERVICE_NAME="veo-production-suite"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "🚀 Starting deployment for $SERVICE_NAME..."

# 1. Build the unified Docker image
echo "📦 Building Docker image..."
docker build -t $IMAGE_NAME .

# 2. Push to Google Container Registry (or Artifact Registry)
echo "📤 Pushing image to registry..."
docker push $IMAGE_NAME

# 3. Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,FIRESTORE_COLLECTION=veogen_projects,OPTIMIZE_PROMPT_MODEL=gemini-3-preview,STORYBOARD_MODEL=imagen/nano-banana,VIDEO_GEN_MODEL=veo-3" \
  --port 8080

echo "✅ Deployment complete!"
