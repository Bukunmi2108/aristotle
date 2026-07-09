#!/usr/bin/env bash
set -euo pipefail

echo "Starting Aristotle agent API"
echo "PORT=${PORT:-7860}"
echo "PRIMARY_MODEL_BASE_URL=${PRIMARY_MODEL_BASE_URL:-https://api-inference.modelscope.ai/v1}"
echo "PRIMARY_MODEL_NAME=${PRIMARY_MODEL_NAME:-Qwen/Qwen3-235B-A22B-Instruct-2507}"
echo "MODEL_FALLBACK_ENABLED=${MODEL_FALLBACK_ENABLED:-true}"
echo "FALLBACK_MODEL_BASE_URL=${FALLBACK_MODEL_BASE_URL:-${ARISTOTLE_MODEL_BASE_URL:-https://bukunmi2108-aristotle-model.hf.space}/v1}"
echo "FALLBACK_MODEL_NAME=${FALLBACK_MODEL_NAME:-${ARISTOTLE_MODEL_NAME:-/models/NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf}}"
echo "ARISTOTLE_SEARCH_BASE_URL=${ARISTOTLE_SEARCH_BASE_URL:-unset}"
echo "DATABASE_URL=${DATABASE_URL:+configured}"

POSTGRES_PID=""
APP_PID=""

postgres_bin_dir() {
    local bin_dir
    bin_dir="$(find /usr/lib/postgresql -maxdepth 4 -type f -name postgres -print -quit 2>/dev/null || true)"
    if [ -z "$bin_dir" ]; then
        echo "Could not find postgres binary" >&2
        exit 1
    fi
    dirname "$bin_dir"
}

as_postgres() {
    runuser -u postgres -- "$@"
}

stop_postgres() {
    if [ -n "${POSTGRES_PID:-}" ]; then
        echo "Stopping internal Postgres"
        as_postgres "$(postgres_bin_dir)/pg_ctl" -D "${PGDATA}" -m fast stop >/dev/null 2>&1 || true
        POSTGRES_PID=""
    fi
}

shutdown() {
    if [ -n "${APP_PID:-}" ]; then
        kill "${APP_PID}" >/dev/null 2>&1 || true
    fi
    stop_postgres
}

start_internal_postgres() {
    export PGDATA="${PGDATA:-/tmp/aristotle-postgres}"
    export POSTGRES_DB="${POSTGRES_DB:-aristotle}"
    export POSTGRES_USER="${POSTGRES_USER:-aristotle}"
    export POSTGRES_PORT="${POSTGRES_PORT:-5432}"

    local pg_bin
    pg_bin="$(postgres_bin_dir)"

    echo "Starting internal ephemeral Postgres"
    echo "PGDATA=${PGDATA}"
    echo "POSTGRES_DB=${POSTGRES_DB}"
    echo "POSTGRES_USER=${POSTGRES_USER}"
    echo "POSTGRES_PORT=${POSTGRES_PORT}"

    mkdir -p "${PGDATA}"
    chown -R postgres:postgres "${PGDATA}"

    if [ ! -s "${PGDATA}/PG_VERSION" ]; then
        echo "Initializing Postgres data directory"
        as_postgres "${pg_bin}/initdb" -D "${PGDATA}" --auth=trust >/dev/null
    fi

    as_postgres "${pg_bin}/pg_ctl" \
        -D "${PGDATA}" \
        -o "-c listen_addresses=127.0.0.1 -p ${POSTGRES_PORT}" \
        -l /tmp/aristotle-postgres.log \
        start >/dev/null

    for attempt in $(seq 1 30); do
        if as_postgres "${pg_bin}/pg_isready" -h 127.0.0.1 -p "${POSTGRES_PORT}" >/dev/null 2>&1; then
            break
        fi
        if [ "$attempt" = "30" ]; then
            echo "Internal Postgres did not become ready" >&2
            cat /tmp/aristotle-postgres.log >&2 || true
            exit 1
        fi
        sleep 1
    done

    if ! as_postgres psql -h 127.0.0.1 -p "${POSTGRES_PORT}" -d postgres -tAc "select 1 from pg_roles where rolname='${POSTGRES_USER}'" | grep -q 1; then
        as_postgres createuser -h 127.0.0.1 -p "${POSTGRES_PORT}" "${POSTGRES_USER}"
    fi

    if ! as_postgres psql -h 127.0.0.1 -p "${POSTGRES_PORT}" -d postgres -tAc "select 1 from pg_database where datname='${POSTGRES_DB}'" | grep -q 1; then
        as_postgres createdb -h 127.0.0.1 -p "${POSTGRES_PORT}" -O "${POSTGRES_USER}" "${POSTGRES_DB}"
    fi

    export DATABASE_URL="postgresql://${POSTGRES_USER}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"
    POSTGRES_PID="$(head -n 1 "${PGDATA}/postmaster.pid" 2>/dev/null || true)"
    echo "Internal Postgres ready"
}

if [ -z "${DATABASE_URL:-}" ]; then
    start_internal_postgres
fi

trap shutdown INT TERM

uv run --frozen uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-7860}" &
APP_PID="$!"

wait "${APP_PID}"
status="$?"
APP_PID=""
stop_postgres
exit "${status}"
