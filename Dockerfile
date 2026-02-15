# --- Stage 1: Build Frontend ---
FROM node:24-slim AS frontend-build
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
ENV OPTIMIZE_PROMPT_MODEL=gemini-3-preview
ENV STORYBOARD_MODEL=imagen/nano-banana
ENV VIDEO_GEN_MODEL=veo-3
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
