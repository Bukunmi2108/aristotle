#!/usr/bin/env bash
set -euo pipefail

: "${MODEL_REPO_ID:?MODEL_REPO_ID is required}"
: "${MODEL_FILENAME:?MODEL_FILENAME is required}"
: "${MODEL_CONTEXT_SIZE:=4096}"
: "${MODEL_THREADS:=2}"
: "${MODEL_PORT:=7860}"

exec llama-server \
    --hf-repo "$MODEL_REPO_ID" \
    --hf-file "$MODEL_FILENAME" \
    --host 0.0.0.0 \
    --port "$MODEL_PORT" \
    --ctx-size "$MODEL_CONTEXT_SIZE" \
    --threads "$MODEL_THREADS"