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
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS builder

# uv resolves and installs from uv.lock, so the image gets byte-identical
# dependencies to CI and to a developer's machine. The uv image carries both a
# version tag and its digest: the version says what this is, the digest is what
# actually decides. An unpinned `:latest` would make the build non-reproducible
# in exactly the way the lock file exists to prevent.
#
# build-only: the two binaries land in `builder`, and `base` copies only the
# resolved /app/.venv out of it. Nothing from this image reaches a running
# container, which is why the CVE scan skips it — see base-image-freshness.yml.
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
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS base

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
    #
    # Only that directory changes owner, never `/app` — the worker stage below
    # explains why. Here it also cost time: overlayfs copies every venv file up
    # on chown, and on the 3.9 GB box that layer took 634 s on 2026-10-05,
    # pushing the deploy past its 20-minute timeout mid-rotation.
    && chown -R appuser:appuser /app/.cache
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
#
# NO `chown -R /app`. It used to be here, and `docker history` priced it at
# 265 MB — overlayfs copies a file up on an ownership change, so recursing over
# the venv duplicated all of it into one layer, twice over (worker and beat).
# Nothing needs it: the worker only READS /app, and beat's one writable file is
# `--schedule=/tmp/celerybeat-schedule` (see the compose command). Root-owned,
# world-readable code that the runtime user cannot rewrite is also the stronger
# arrangement of the two.
RUN useradd --create-home --uid 10002 celeryuser
USER celeryuser

# Liveness via Celery's own ping to the broker-connected worker.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD celery -A src.core.celery_app.celery_app inspect ping || exit 1

# `--concurrency=2`, not 4, and `--max-tasks-per-child` on top. Both are memory
# decisions rather than throughput ones, and both were bought with an OOM.
#
# Every child is a whole Python process with the whole app loaded. Measured in
# production 2026-09-15 against the 768 MiB cap in compose: parent 212 MB, four
# children 129-153 MB each, so the pool idled at ~500 MB — 65% of the cap spent
# before any task ran. A streamed settlement page then needed more than the
# ~270 MB left and the kernel took the worker (SIGKILL, anon-rss 417 MB).
#
# Four was buying nothing anyway. This pool's work is I/O bound and paced by WB
# itself — the settlement endpoint serves about four requests an HOUR — so the
# rate gates serialise the expensive tasks whatever the concurrency is. What the
# extra children did buy was four simultaneous chances to be the one that runs
# out of memory.
#
# `--max-tasks-per-child` is the other half. CPython returns freed memory to the
# OS only sometimes, so a child that has handled one 100 000-row page keeps its
# high-water RSS for ever, and the pool's floor ratchets upward all day. That is
# why the same page succeeded at 07:20 on a freshly restarted worker and was
# killed at 09:17 on the same code: nothing had changed but the baseline.
# Recycling a child bounds the ratchet without anyone having to notice it.
#
# `--max-memory-per-child` is the backstop over the top of it, and it is the one
# that actually decides who ends the process. A task count is a proxy for memory
# growth and a bad one: measured on prod 2026-09-17, two children of the same
# age sat at 220 MB and 148 MB, because what a child has held matters and how
# many times it has held something does not. Three SIGKILLs in the twelve hours
# to 01:06 that day — one in `guide.capture_daily`, two in the finance harvest —
# were all a child that had already ratcheted past 500 MB meeting an ordinary
# allocation.
#
# 220 MB — and how that number is arrived at is worth more than the number,
# because the first attempt at it was 300 and 300 is what let the 09-18 outage
# happen. Celery reads KiB and compares the child's PEAK RSS after each task, so
# a child that spikes once is retired even if it has since shrunk.
#
# **The limit does not cap what a task may allocate. It caps the FLOOR the next
# task has to fit above.** The check runs between tasks, so a single task that
# needs more than the cgroup has left is killed by the kernel regardless of what
# is written here — which is exactly what happened twenty-one times on 09-18.
# What the limit decides is how much of the 768 MiB is already spoken for when
# that task starts.
#
# The arithmetic, in the only units that matter. The cgroup counts a page shared
# by fork once, so it is not the sum of the RSS figures: a fresh pool reads
# 294 MB in `memory.current` while its three processes report 439 MB between
# them. Per child, ~147 MB of that is shared with the parent and the rest is its
# own. So the floor a limit L permits is roughly `parent + 2 x (L - 147)`:
#
#   L = 300  ->  156 + 2 x 153  =  ~562 MB   (measured before the 09-19 reboot:
#                                             554 MB. The model was right and
#                                             the number was still wrong.)
#   L = 220  ->  156 + 2 x  73  =  ~302 MB
#
# That is the whole change: ~250 MB more room for whatever a task legitimately
# needs, bought by recycling children sooner.
#
# What it costs is a fork — cheap, from a parent that has already imported
# everything — and the child's warm state: its Postgres pool, its Redis pool,
# its HTTP clients. Once an hour that is nothing; once a minute it would be
# connection churn. The measured growth per task says it will be rare:
# `celery_task_memory_growth_bytes` over 48 h puts `ab_tests.poll_rotations` at
# 4.3 MB, `refresh_buyout_cohorts` at 2.9 MB and `sweep_stalled_backfills` at
# 0.3 MB. The one outlier was `harvest_finance` at 369 MB, and that was the
#
# Lowering this was NOT the fix for 09-18 and must not be read as one — the fix
# was not materialising 115 366 rows. This is what stops the next unbudgeted
# allocation meeting a floor that has already eaten two thirds of the box.
#
# The difference the limit buys at all: Celery retires a child BETWEEN tasks,
# cleanly, and the next task runs in a new one. The kernel does it mid-task,
# with a SIGKILL, and `acks_on_failure_or_timeout` then acknowledges the message
# — so the work is not requeued, it is simply gone until the next tick.
CMD ["celery", "-A", "src.core.celery_app.celery_app", "worker", \
     "--loglevel=INFO", "--concurrency=2", "--max-tasks-per-child=100", \
     "--max-memory-per-child=225280"]
