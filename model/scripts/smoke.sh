#!/usr/bin/env bash
set -euo pipefail

BASE_URL = "${MODEL_BASE_URL:-http://localhost:8200}"

curl -s "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "aristotle-local",
        "messages": [
        {"role": "user", "content": "Reply with exactly: model-ok"}
        ],
        "max_tokens": 16
    }'