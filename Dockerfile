# --- Stage 1: Build Frontend ---
FROM node:24-slim AS frontend-build
ARG VITE_GUEST_INVITE_CODE=""
ENV VITE_GUEST_INVITE_CODE=$VITE_GUEST_INVITE_CODE
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --registry=https://registry.npmjs.org/
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Build Backend & Bundle ---
FROM python:3.12-slim
WORKDIR /app

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
WORKDIR /app/api

# Copy frontend build from Stage 1 into the 'static' folder
COPY --from=frontend-build /app/frontend/dist ./static

# Expose port (Cloud Run sets $PORT environment variable)
ENV PORT=8080
ENV OPTIMIZE_PROMPT_MODEL=gemini-3.1-pro-preview
ENV STORYBOARD_MODEL=gemini-3.1-flash-image-preview
ENV VIDEO_GEN_MODEL=veo-3.1-generate-001
ENV GEMINI_AGENT_ORCHESTRATOR=gemini-3.1-flash-lite-preview
ENV GOOGLE_GENAI_USE_VERTEXAI=true
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
