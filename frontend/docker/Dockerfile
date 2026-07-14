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

FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies first so source edits don't bust the npm cache layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# No VITE_API_URL is passed on purpose: the axios client defaults to the
# relative `/api`, which nginx proxies to the backend on the same origin.
RUN npm run build

# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Replace the stock default server with our SPA + reverse-proxy config.
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80 443

# Probe the plain-HTTP /healthz endpoint: it returns 200 without redirecting,
# so the check never chases a 301 into TLS (the cert is for example.com,
# not localhost).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://localhost/healthz || exit 1
