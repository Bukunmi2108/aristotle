#!/usr/bin/env bash
set -eu

echo "Starting Aristotle sandbox service"
echo "PORT=${PORT:-7860}"
echo "SANDBOX_WORKSPACE_ROOT=${SANDBOX_WORKSPACE_ROOT:-/workspace}"

exec uv run --frozen uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-7860}"
