#!/usr/bin/env bash
set -eu

echo "Starting Aristotle agent API"
echo "PORT=${PORT:-7860}"
echo "ARISTOTLE_MODEL_BASE_URL=${ARISTOTLE_MODEL_BASE_URL:-unset}"
echo "ARISTOTLE_SEARCH_BASE_URL=${ARISTOTLE_SEARCH_BASE_URL:-unset}"

exec uv run --frozen uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-7860}"
