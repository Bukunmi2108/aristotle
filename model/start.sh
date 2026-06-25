#!/usr/bin/env bash
set -euo pipefail

: "${MODEL_REPO_ID:?MODEL_REPO_ID is required}"
: "${MODEL_FILENAME:?MODEL_FILENAME is required}"
: "${MODEL_CONTEXT_SIZE:=4096}"
: "${MODEL_THREADS:=2}"
: "${MODEL_PARALLEL:=1}"
: "${MODEL_PORT:=7860}"
: "${MODEL_DIR:=/models}"

mkdir -p "$MODEL_DIR"

MODEL_PATH="$MODEL_DIR/$MODEL_FILENAME"
MODEL_URL="https://huggingface.co/$MODEL_REPO_ID/resolve/main/$MODEL_FILENAME"
MODEL_PART_PATH="$MODEL_PATH.part"

echo "============================================================"
echo "Aristotle model service startup"
echo "============================================================"
echo "Model configuration:"
echo "  MODEL_REPO_ID=$MODEL_REPO_ID"
echo "  MODEL_FILENAME=$MODEL_FILENAME"
echo "  MODEL_DIR=$MODEL_DIR"
echo "  MODEL_PATH=$MODEL_PATH"
echo "  MODEL_URL=$MODEL_URL"
echo "  MODEL_CONTEXT_SIZE=$MODEL_CONTEXT_SIZE"
echo "  MODEL_THREADS=$MODEL_THREADS"
echo "  MODEL_PARALLEL=$MODEL_PARALLEL"
echo "  MODEL_PORT=$MODEL_PORT"
if [[ -n "${HF_TOKEN:-}" ]]; then
    echo "  HF_TOKEN=present"
else
    echo "  HF_TOKEN=not set"
fi
echo "============================================================"

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "Model file is not present. Starting download."
    echo "Download destination:"
    echo "  final:   $MODEL_PATH"
    echo "  partial: $MODEL_PART_PATH"

    curl_args=(
        --location
        --fail
        --show-error
        --progress-bar
        --retry 3
        --retry-delay 5
        --connect-timeout 30
        --continue-at -
    )

    if [[ -n "${HF_TOKEN:-}" ]]; then
        curl_args+=(--header "Authorization: Bearer $HF_TOKEN")
    fi

    echo "Running download command:"
    echo "  curl --location --fail --show-error --progress-bar --retry 3 --retry-delay 5 --connect-timeout 30 --continue-at - [auth-header-if-present] \"$MODEL_URL\" --output \"$MODEL_PART_PATH\""
    curl "${curl_args[@]}" "$MODEL_URL" --output "$MODEL_PART_PATH"
    mv "$MODEL_PART_PATH" "$MODEL_PATH"
    echo "Download complete."
else
    echo "Model file already exists. Using cached model:"
    echo "  $MODEL_PATH"
fi

if [[ ! -s "$MODEL_PATH" ]]; then
    echo "ERROR: model file is missing or empty: $MODEL_PATH" >&2
    exit 1
fi

echo "Model file details:"
ls -lh "$MODEL_PATH"
echo "Disk usage:"
du -h "$MODEL_PATH"

echo "Starting llama-server:"
echo "  llama-server --model \"$MODEL_PATH\" --host 0.0.0.0 --port \"$MODEL_PORT\" --ctx-size \"$MODEL_CONTEXT_SIZE\" --parallel \"$MODEL_PARALLEL\" --threads \"$MODEL_THREADS\""
echo "============================================================"

exec llama-server \
    --model "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port "$MODEL_PORT" \
    --ctx-size "$MODEL_CONTEXT_SIZE" \
    --parallel "$MODEL_PARALLEL" \
    --threads "$MODEL_THREADS"
