# kairos-evolve-api — AWS App Runner image.
# Mirrors the kairos gateway's uv-based Dockerfile (kairos repo deploy/Dockerfile).
# App Runner runs the FastAPI app via the build_app() ASGI factory (the module
# has no importable `app` — `app = None` is intentional), so we use
# `uvicorn --factory`. The long-GEPA worker (#35) is a separate ECS-Fargate/Batch
# image, NOT this one.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# uv for fast, locked installs.
RUN pip install --no-cache-dir uv

# Resolve deps from the lockfile first (cache-friendly), then the source.
# README.md is required: pyproject `readme = "README.md"` makes the hatchling
# build read it during `uv sync`.
COPY pyproject.toml uv.lock* README.md ./
COPY packages/ packages/
# Install the project + the [api] extra (fastapi/uvicorn/psycopg/...). Fall back
# to a non-frozen sync if the lockfile drifts from pyproject.
RUN uv sync --frozen --extra api 2>/dev/null || uv sync --extra api

EXPOSE 8000

# App Runner health check hits /readyz (DB-aware: SELECT 1). The factory pattern
# avoids importing the module-level `app = None`.
CMD ["uv", "run", "uvicorn", "kairos_evolve.api.app:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
