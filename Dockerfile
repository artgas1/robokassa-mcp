# syntax=docker/dockerfile:1.6
#
# Multi-stage image for robokassa-mcp.
#
# Build: uv assembles a virtualenv with only runtime deps.
# Runtime: distroless-ish slim image that runs `robokassa-mcp` as the default
# entrypoint. Stdio transport by default; override with CMD for HTTP.

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python${PYTHON_VERSION}

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only what's needed for dependency resolution first (layer caching).
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/

# Install the package + runtime deps into a project venv.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:${PYTHON_VERSION}-slim AS runtime

# Create a non-root user so the container doesn't run as root.
RUN useradd --create-home --shell /bin/bash --uid 1000 robokassa

WORKDIR /app

COPY --from=builder --chown=robokassa:robokassa /app /app

USER robokassa

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Stdio transport by default — matches Claude Desktop's expectation.
# For HTTP: `docker run ... robokassa-mcp --transport http --host 0.0.0.0`
ENTRYPOINT ["robokassa-mcp"]
