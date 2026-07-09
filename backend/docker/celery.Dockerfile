# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Celery worker image.
# Shares the exact dependency build as the app image, but its entrypoint boots a
# Celery worker instead of the ASGI server. Kept as a separate Dockerfile so the
# worker can scale and be resource-tuned independently of the API.
# ---------------------------------------------------------------------------

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install "psycopg[binary]" \
    && pip install .

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY . .

RUN useradd --create-home --uid 10002 celeryuser \
    && chown -R celeryuser:celeryuser /app
USER celeryuser

# Liveness via Celery's own ping to the broker-connected worker.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD celery -A src.core.celery_app.celery_app inspect ping || exit 1

CMD ["celery", "-A", "src.core.celery_app.celery_app", "worker", \
     "--loglevel=INFO", "--concurrency=4"]
