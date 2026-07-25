FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PORT=7860
# Put the project venv first on PATH so user commands (`python3`, `pip`) resolve
# to the same interpreter that carries the data/runtime stack installed below.
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Runtime toolchain available to executed code: node/npm for JS builds and a
# C toolchain for native extensions. Kept minimal on top of python:3.12-slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nodejs npm build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/

# Service deps (lean) then the user-facing data stack into the same venv, so
# executed code can `import pandas`/`numpy`/`matplotlib` out of the box.
RUN uv sync --frozen --no-dev --no-install-project \
    && uv pip install --no-cache pandas numpy matplotlib

COPY app /app/app
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Run as a non-root user. This is one layer of the isolation story; the others
# (dropped caps, private network, cgroup caps) are set by the compose file.
RUN useradd --create-home --uid 10001 sandbox \
    && mkdir -p /workspace \
    && chown -R sandbox:sandbox /workspace /app
USER sandbox

EXPOSE 7860

CMD ["/app/start.sh"]
