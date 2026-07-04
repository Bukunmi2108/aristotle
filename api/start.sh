#!/usr/bin/env bash
set -eu

echo "Starting Aristotle agent API"
echo "PORT=${PORT:-7860}"
echo "PRIMARY_MODEL_BASE_URL=${PRIMARY_MODEL_BASE_URL:-https://api-inference.modelscope.ai/v1}"
echo "PRIMARY_MODEL_NAME=${PRIMARY_MODEL_NAME:-Qwen/Qwen3-235B-A22B-Instruct-2507}"
echo "MODEL_FALLBACK_ENABLED=${MODEL_FALLBACK_ENABLED:-true}"
echo "FALLBACK_MODEL_BASE_URL=${FALLBACK_MODEL_BASE_URL:-${ARISTOTLE_MODEL_BASE_URL:-https://bukunmi2108-aristotle-model.hf.space}/v1}"
echo "FALLBACK_MODEL_NAME=${FALLBACK_MODEL_NAME:-${ARISTOTLE_MODEL_NAME:-/models/NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf}}"
echo "ARISTOTLE_SEARCH_BASE_URL=${ARISTOTLE_SEARCH_BASE_URL:-unset}"

exec uv run --frozen uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-7860}"
