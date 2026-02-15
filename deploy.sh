#!/bin/bash
set -e

# Configuration
PROJECT_ID="random-poc-479104"
REGION="asia-south1"
GCS_BUCKET="superexam-uploads"
SERVICE_NAME="veo-production-suite"
IMAGE_NAME="asia-south1-docker.pkg.dev/$PROJECT_ID/superexam-repo/$SERVICE_NAME"

echo "🧪 Running Local Pre-flight Checks..."

# --- 1. Frontend Verification ---
echo "🎨 Verifying Frontend Build..."
cd frontend
# Use 'npm ci' if package-lock.json exists for faster/cleaner install, else 'npm install'
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
# Create a temp venv to avoid polluting system
python3 -m venv .deploy_venv
source .deploy_venv/bin/activate
pip install -q -r api/requirements.txt

# Export env vars required for startup
export GOOGLE_CLOUD_PROJECT=$PROJECT_ID
export GCS_BUCKET=$GCS_BUCKET
export FIRESTORE_COLLECTION="veogen_projects"
export OPTIMIZE_PROMPT_MODEL="gemini-3-preview"
export STORYBOARD_MODEL="imagen/nano-banana"
export VIDEO_GEN_MODEL="veo-3"
export PORT=8081

# Start API in background
echo "   Starting API locally on port $PORT..."
python api/main.py > /dev/null 2>&1 &
API_PID=$!

# Wait for startup (5 seconds)
sleep 5

# Check if process is still running
if kill -0 $API_PID 2>/dev/null; then
    echo "✅ API started successfully."
    kill $API_PID
else
    echo "❌ API failed to start locally."
    # Cleanup
    deactivate
    rm -rf .deploy_venv
    exit 1
fi

# Cleanup
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
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,FIRESTORE_COLLECTION=veogen_projects,OPTIMIZE_PROMPT_MODEL=gemini-3-preview,STORYBOARD_MODEL=imagen/nano-banana,VIDEO_GEN_MODEL=veo-3" \
  --port 8080

echo "✅ Deployment complete!"
