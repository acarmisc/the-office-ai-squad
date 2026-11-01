# syntax=docker/dockerfile:1
# code-squad image: one image for every agent, AGENT_NAME selects the role.
#
# Local build:       docker build -f deploy/Dockerfile -t code-squad:dev .
# Multi-arch build:  docker buildx build -f deploy/Dockerfile --platform linux/amd64,linux/arm64 -t code-squad:dev .

# Base image is a build argument so air-gapped builds can point at a mirror.
ARG PYTHON_IMAGE=python:3.12-slim

# ---------------------------------------------------------------------------
# Builder: resolve and install locked dependencies with uv. No runtime leaks
# from here except /app/.venv and /app/src.
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer first, so source edits do not invalidate it. The project itself
# is not installed yet (README.md is needed by the hatchling build metadata).
COPY pyproject.toml uv.lock README.md ./
# The redis extra is included so that SESSION_STORE_URL=redis://... works without a rebuild.
RUN uv sync --frozen --no-dev --extra redis --no-install-project

# Project source, installed editable into the same venv (points at /app/src).
COPY src/ ./src/
RUN uv sync --frozen --no-dev --extra redis

# ---------------------------------------------------------------------------
# Runtime: no compilers, no uv, no source tree beyond what the app imports.
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# tini: PID 1 signal forwarding and zombie reaping.
# git: needed by the local sandbox (clone, diff, apply patch).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Fixed non-root identity (uid 10001). No home directory: HOME points at /tmp,
# which is an emptyDir in Kubernetes because the root filesystem is read-only.
RUN groupadd --system --gid 10001 squad \
    && useradd --system --uid 10001 --gid 10001 \
        --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin squad

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Offline LLM stub, used by deploy/compose.yaml and the kind demo
# (`python -m deploy.fake_llm`). Copied explicitly so nothing else from deploy/ ships.
COPY deploy/__init__.py /app/deploy/__init__.py
COPY deploy/fake_llm/ /app/deploy/fake_llm/

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=4).close()"]

USER 10001:10001

ENTRYPOINT ["tini", "--", "uvicorn", "code_squad.server:app", "--host", "0.0.0.0", "--port", "8080"]
