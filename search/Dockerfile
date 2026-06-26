FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV SEARXNG_SETTINGS_PATH=/app/searxng/settings.yml
ENV SEARXNG_INTERNAL_URL=http://127.0.0.1:8080
ENV PORT=7860

RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    git \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

ARG SEARXNG_REF=master

COPY searxng /app/searxng

RUN git clone --depth 1 --branch "$SEARXNG_REF" https://github.com/searxng/searxng.git /opt/searxng \
    && python -m venv /opt/searxng-venv \
    && /opt/searxng-venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/searxng-venv/bin/pip install -r /opt/searxng/requirements.txt \
    && /opt/searxng-venv/bin/pip install --no-build-isolation -e /opt/searxng

WORKDIR /app

COPY pyproject.toml uv.lock /app/

RUN uv sync --frozen --no-dev --no-install-project

COPY app /app/app
COPY start.sh /app/start.sh

RUN chmod +x /app/start.sh

EXPOSE 7860

CMD ["/app/start.sh"]
