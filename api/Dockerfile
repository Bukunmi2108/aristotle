FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PORT=7860

WORKDIR /app

COPY pyproject.toml uv.lock /app/

RUN uv sync --frozen --no-dev --no-install-project

COPY app /app/app
COPY start.sh /app/start.sh

RUN chmod +x /app/start.sh

EXPOSE 7860

CMD ["/app/start.sh"]
