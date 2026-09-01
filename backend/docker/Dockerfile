# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# One Dockerfile, two runtime images.
#
# The API and the Celery worker run the same code with the same dependencies —
# they differ only in the process they start, the healthcheck that proves it is
# alive, and the uid it runs as. Two Dockerfiles meant those ~50 shared lines
# were copied, and drifted: the comments describing the runtime `apt` layer had
# already diverged even though the layer itself was identical.
#
# Build a specific image with `--target`:
#
#     docker build -f docker/Dockerfile --target api    -t marketplace-api .
#     docker build -f docker/Dockerfile --target worker -t marketplace-worker .
#
# docker-compose.yml selects them the same way (`build.target`). They still
# scale and are resource-tuned independently — that was never a property of
# having separate files.
# ---------------------------------------------------------------------------

# --------------------------------------------------------------------- builder
# Base images are pinned by DIGEST, not by tag. `python:3.12-slim` is a moving
# target — the same tag is re-pushed on every patch release — so an image built
# from it today and one built next week are different images with the same name,
# and neither the lock file nor CI can tell. The digest makes the base as
# reproducible as the dependencies uv resolves into it (register P1.8).
#
# The cost is that a digest goes stale: pinning opts OUT of the automatic
# security patches a floating tag delivers. That is why `.github/workflows/
# base-image-freshness.yml` fails once a week when a pin has drifted from its
# tag — refreshing is meant to be a deliberate act with a diff, not an accident
# of whenever a build happened to run.
FROM python:3.12-slim@sha256:e5c9fa26ffb76e11e0f054f30dc2523a2f9693f0c36c0cf1e39b27e152d899fc AS builder

# uv resolves and installs from uv.lock, so the image gets byte-identical
# dependencies to CI and to a developer's machine. The uv image carries both a
# version tag and its digest: the version says what this is, the digest is what
# actually decides. An unpinned `:latest` would make the build non-reproducible
# in exactly the way the lock file exists to prevent.
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Build toolchain needed to compile any sdist-only dependency (asyncpg, bcrypt
# ship wheels, but a transitive one may not).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, in their own layer: they change far less often than the
# source, so editing a router does not re-resolve the whole environment.
# --no-install-project installs ONLY the dependencies here; the project itself
# lands in the next layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# Now the application itself.
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY main.py ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---------------------------------------------------------------- runtime base
# Everything both images share. Neither `base` nor anything below re-installs a
# dependency — they only copy the environment the builder resolved.
FROM python:3.12-slim@sha256:e5c9fa26ffb76e11e0f054f30dc2523a2f9693f0c36c0cf1e39b27e152d899fc AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# libpq5 for asyncpg/psycopg. curl serves two purposes: the API's container
# healthcheck, and the worker's storefront customer-price fetch — WB's
# card.wb.ru anti-bot edge blocks Python's TLS fingerprint but admits a real
# curl (see integrations/wildberries/clients/card.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY . .

# ------------------------------------------------------------------------- api
FROM base AS api

RUN useradd --create-home --uid 10001 appuser \
    # runtime user. Docker seeds a fresh named volume from the image's directory
    # at that path, ownership included; with no such directory the volume is
    # created root-owned and the unprivileged process cannot write to it. The
    # service degrades to rebuilding on every request when that happens — the
    # download still works, so the only symptom is silently losing the cache.
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------- worker
FROM base AS worker

# A distinct uid from the API's: the two containers share no writable state, and
# keeping them apart means a compromised worker cannot touch anything the API
# process owns.
RUN useradd --create-home --uid 10002 celeryuser \
    && chown -R celeryuser:celeryuser /app
USER celeryuser

# Liveness via Celery's own ping to the broker-connected worker.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD celery -A src.core.celery_app.celery_app inspect ping || exit 1

CMD ["celery", "-A", "src.core.celery_app.celery_app", "worker", \
     "--loglevel=INFO", "--concurrency=4"]
