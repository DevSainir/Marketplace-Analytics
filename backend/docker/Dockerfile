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
FROM python:3.12-slim AS builder

# uv resolves and installs from uv.lock, so the image gets byte-identical
# dependencies to CI and to a developer's machine. Pinned by digest-bearing tag:
# an unpinned `:latest` would make the build non-reproducible in exactly the way
# the lock file exists to prevent.
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

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
FROM python:3.12-slim AS base

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

# -------------------------------------------------------------- session_minter
# A browser, kept OUT of the api and worker images on purpose.
#
# Only one job needs Chromium — minting the WB storefront session once a day —
# and it needs it for a few seconds. Installing it into the worker would put
# ~400 MB of browser into an image that runs every harvest, on a host with 2 GB
# free; here it stays in a stage nothing else pulls, started on a schedule and
# gone again.
#
# playwright's own chromium build rather than the distro package: the Python
# package pins the protocol version it drives, and a distro chromium that
# upgrades underneath it breaks with an unhelpful handshake error.
FROM base AS session_minter

USER root

# One shared browser directory, owned by the runtime user. Chromium is ~450 MB;
# installing to the default per-user cache and then copying it to the minter's
# home stored it TWICE and pushed the image to 3.6 GB.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# The shared libraries Chromium needs, named explicitly for Debian.
#
# NOT `playwright install --with-deps`: it detects an unsupported OS, falls back
# to its Ubuntu 20.04 package list, and dies on packages Debian does not carry
# ("Package 'ttf-unifont' has no installation candidate", surfacing as a bare
# exit code 100). Listing them here also documents what a headless browser
# actually costs this image.
#
# `python -m pip`, not `pip`: PATH puts the uv-built venv first, so `python` is
# the venv's — but uv does not install pip INTO the venv, so a bare `pip` is the
# system one and playwright lands where the venv cannot see it. That failure
# arrives much later, as ModuleNotFoundError at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
        libcups2 libdrm2 libgbm1 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libpango-1.0-0 libcairo2 libasound2 \
        fonts-liberation \
    && python -m ensurepip --upgrade \
    && python -m pip install --no-cache-dir playwright==1.49.1 \
    && python -m playwright install chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache

RUN useradd --create-home --uid 10003 minter \
    && chown -R minter:minter /app /opt/ms-playwright
USER minter

# One shot: mint, store, exit. Scheduled from the host's crontab beside the
# backup jobs, not from Celery beat — the browser lives in this image, and the
# worker has no way to launch it.
CMD ["python", "-m", "scripts.mint_search_session"]
