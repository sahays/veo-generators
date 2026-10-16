#!/bin/bash
set -e

export FASTAPI_INTERNAL_HOST="127.0.0.1"
export FASTAPI_INTERNAL_PORT="8000"
export FASTAPI_INTERNAL_ORIGIN="http://127.0.0.1:8000"
EXTERNAL_PORT="${PORT:-8080}"

echo "🚀 Starting FastAPI internal backend on 127.0.0.1:${FASTAPI_INTERNAL_PORT}..."
cd /app/api
PORT="${FASTAPI_INTERNAL_PORT}" uvicorn main:app --host 127.0.0.1 --port "${FASTAPI_INTERNAL_PORT}" &
FASTAPI_PID=$!

echo "⏳ Waiting for FastAPI internal backend (127.0.0.1:${FASTAPI_INTERNAL_PORT}/health) before opening Cloud Run port ${EXTERNAL_PORT}..."
for i in $(seq 1 120); do
  if ! kill -0 "$FASTAPI_PID" 2>/dev/null; then
    echo "❌ FastAPI process exited prematurely!"
    wait "$FASTAPI_PID"
    exit 1
  fi
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${FASTAPI_INTERNAL_PORT}/health', timeout=1)" >/dev/null 2>&1; then
    echo "✅ FastAPI internal backend is ready on 127.0.0.1:${FASTAPI_INTERNAL_PORT}."
    break
  fi
  sleep 0.5
done

echo "⚡ Starting Next.js SSR standalone server on 0.0.0.0:${EXTERNAL_PORT}..."
cd /app/frontend-standalone
PORT="${EXTERNAL_PORT}" HOSTNAME="0.0.0.0" node start-standalone.cjs &
NEXT_PID=$!

trap "kill -TERM $FASTAPI_PID $NEXT_PID 2>/dev/null || true" SIGTERM SIGINT

wait -n $FASTAPI_PID $NEXT_PID
EXIT_CODE=$?
kill -TERM $FASTAPI_PID $NEXT_PID 2>/dev/null || true
exit $EXIT_CODE
