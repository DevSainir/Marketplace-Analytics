# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Frontend image: multi-stage build.
# Stage 1 installs npm dependencies and builds the Vite `dist`.
# Stage 2 is a plain nginx that serves the static bundle and reverse-proxies
# /api/ to the backend container (single entry point — see nginx.conf).
#
# Build context is the frontend/ directory:
#   docker build -f docker/Dockerfile .
# ---------------------------------------------------------------------------

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
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS builder

WORKDIR /app

# Install dependencies first so source edits don't bust the npm cache layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# No VITE_API_URL is passed on purpose: the axios client defaults to the
# relative `/api`, which nginx proxies to the backend on the same origin.
RUN npm run build

# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10 AS runtime

# Replace the stock default server with our SPA + reverse-proxy config.
# The snippets carry the response security headers, which every location that
# sets its own cache header has to re-include (see snippets/security-headers.conf).
COPY docker/snippets/ /etc/nginx/snippets/
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80 443

# Probe the plain-HTTP /healthz endpoint: it returns 200 without redirecting,
# so the check never chases a 301 into TLS (the cert is for example.com,
# not localhost). 127.0.0.1, not localhost: busybox wget prefers ::1 while
# nginx binds IPv4 only, so "localhost" is a guaranteed connection-refused.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
