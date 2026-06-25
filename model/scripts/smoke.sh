#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MODEL_BASE_URL:-http://localhost:8200}"
MODEL_NAME="${MODEL_NAME:-/models/Qwen3-8B-Q4_K_M.gguf}"

curl -s "$BASE_URL/v1/models"

curl -s "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{
        \"model\": \"$MODEL_NAME\",
        \"messages\": [
        {\"role\": \"user\", \"content\": \"/no_think Reply with exactly: model-ok\"}
        ],
        \"max_tokens\": 64
    }"
