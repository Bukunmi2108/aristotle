FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PORT=7860
ENV PGDATA=/tmp/aristotle-postgres

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/

RUN uv sync --frozen --no-dev --no-install-project

COPY app /app/app
COPY start.sh /app/start.sh

RUN chmod +x /app/start.sh

EXPOSE 7860

CMD ["/app/start.sh"]
