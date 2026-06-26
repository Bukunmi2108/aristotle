#!/usr/bin/env bash
set -eu

echo "Starting Aristotle search service"
echo "SEARXNG_INTERNAL_URL=${SEARXNG_INTERNAL_URL:-http://127.0.0.1:8080}"
echo "PORT=${PORT:-7860}"

export SEARXNG_SETTINGS_PATH="${SEARXNG_SETTINGS_PATH:-/app/searxng/settings.yml}"

echo "Starting SearXNG on 127.0.0.1:8080"
/opt/searxng-venv/bin/python -m searx.webapp & SEARXNG_PID="$!"

echo "Waiting for SearXNG"
for i in $(seq 1 60); do
    if curl -fsS -H "X-Real-IP: 127.0.0.1" "${SEARXNG_INTERNAL_URL:-http://127.0.0.1:8080}/" >/dev/null 2>&1; then
        echo "SearXNG is reachable"
        break
    fi

    if ! kill -0 "$SEARXNG_PID" >/dev/null 2>&1; then
        echo "SearXNG exited before becoming ready"
        exit 1
    fi

    sleep 1
done

echo "Starting FastAPI wrapper on 0.0.0.0:${PORT:-7860}"
exec uv run --frozen uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-7860}"
