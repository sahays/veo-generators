# --- Stage 1: Build Frontend ---
FROM node:24-slim AS frontend-build
ARG VITE_GUEST_INVITE_CODE=""
ENV VITE_GUEST_INVITE_CODE=$VITE_GUEST_INVITE_CODE
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --registry=https://registry.npmjs.org/
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Build Backend & Bundle Next.js SSR Standalone ---
FROM python:3.12-slim
WORKDIR /app

# Copy Node.js runtime from Stage 1 for Next.js SSR server
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY api/ ./api
COPY productions_service/ ./productions_service

# Copy Next.js standalone SSR build, static assets, and public folder
COPY --from=frontend-build /app/frontend/.next/standalone ./frontend-standalone
COPY --from=frontend-build /app/frontend/.next/static ./frontend-standalone/.next/static
COPY --from=frontend-build /app/frontend/public ./frontend-standalone/public
COPY frontend/start-standalone.cjs ./frontend-standalone/start-standalone.cjs
COPY scripts/start-api-ssr.sh /app/start-api-ssr.sh
RUN chmod +x /app/start-api-ssr.sh

WORKDIR /app/api

# Expose port (Cloud Run sets $PORT environment variable)
ENV PORT=8080
ENV FASTAPI_INTERNAL_ORIGIN=http://127.0.0.1:8000
ENV OPTIMIZE_PROMPT_MODEL=gemini-3.8-flash
ENV STORYBOARD_MODEL=gemini-nano-banana-2.1
ENV ADAPTS_MODEL=gemini-nano-banana-2.1
ENV VIDEO_GEN_MODEL=gemini-omni-1.1-flash-preview
ENV GEMINI_AGENT_ORCHESTRATOR=gemini-3.5-flash-lite
ENV AVATAR_LIVE_MODEL=gemini-3.8-live
ENV AVATAR_LIVE_LOCATION=us
ENV GOOGLE_GENAI_USE_VERTEXAI=true
EXPOSE 8080

# Run FastAPI (127.0.0.1:8000) + Next.js SSR Server (0.0.0.0:$PORT)
CMD ["/app/start-api-ssr.sh"]

