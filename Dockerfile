# Multi-stage: build the static dashboard, then run the Python API that serves it.
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git util-linux && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY evals ./evals
COPY --from=web /app/web/out ./web/out
ENV EVOX_LLM=mock PYTHONUNBUFFERED=1
EXPOSE 8000
# Research-only: the container has no exchange credentials and no order-routing code.
CMD ["uv", "run", "--no-dev", "evox", "serve", "--host", "0.0.0.0", "--port", "8000"]
