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
# reproducible as the dependencies uv resolves into it.
#
# The cost is that a digest goes stale: pinning opts OUT of the automatic
# security patches a floating tag delivers. That is why `.github/workflows/
# base-image-freshness.yml` fails once a week when a pin has drifted from its
# tag — refreshing is meant to be a deliberate act with a diff, not an accident
# of whenever a build happened to run.
#
# build-only: this stage runs `npm ci` and Vite, and the `release` stage below
# takes /app/dist out of it. The image itself — Node, and the npm tree bundled
# with it — is never started anywhere. The CVE scan skips it for that reason;
# the freshness check above still covers it.
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS builder

WORKDIR /app

# Install dependencies first so source edits don't bust the npm cache layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# No VITE_API_URL is passed on purpose: the axios client defaults to the
# relative `/api`, which nginx proxies to the backend on the same origin.
RUN npm run build

# ---------------------------------------------------------------------------
# The RELEASE payload: everything nginx serves, and nothing that runs it.
#
# `FROM scratch`, because this stage is never started as a container. It is
# extracted to a directory with BuildKit's local exporter:
#
#   docker build --target release -o type=local,dest=<dir> frontend/
#
# and the deploy installs that directory beside the previous one (`make
# frontend-release` does the same locally). Keeping the bundle OUT of the runtime image
# below is the entire point: a new SPA build then leaves the runtime image
# byte-identical, so `docker compose up -d frontend` is a no-op and the one
# nginx container holding :443 is never recreated. It used to be recreated on
# every deploy that touched the SPA, and that was a hard 1-3s outage of the
# whole site — the API pool could not help, because nginx is what fronts it.
#
# `app.conf`, not `default.conf`: the nginx image's own
# /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh rewrites a file at that
# exact path, and here it would be rewriting a read-only bind mount.
FROM scratch AS release
COPY docker/snippets/ /snippets/
COPY docker/nginx.conf /conf.d/app.conf
COPY --from=builder /app/dist /html/

# ---------------------------------------------------------------------------
# `-slim`: the full image adds curl, brotli and the njs/xslt/geoip modules,
# none of which this config loads — and with them, fixable CVEs that the
# weekly base-image scan fails on while the slim build of the same nginx is
# clean (2026-10-26).
FROM nginx:1.30-alpine-slim@sha256:dede8895648b461178c3bc604f7eed4423efe5220b2c4d839f5eb3d34ac3f8f7 AS runtime

# The stock server, removed with nothing put in its place — the config arrives
# with the release. /etc/nginx/conf.d and /etc/nginx/snippets become symlinks
# into it, created at container start (see entrypoint-release.sh) rather than
# here, so that one image can serve either the host release directory or a
# baked-in one.
RUN rm -rf /etc/nginx/conf.d /usr/share/nginx/html
# --chmod, not the file's own mode: the nginx image's entrypoint SKIPS anything
# in /docker-entrypoint.d that is not executable — it logs one "ignoring" line
# and starts nginx anyway. The container would then come up with no config at
# all, from a checkout where git happened not to carry the executable bit.
# Setting it here makes the image independent of that.
COPY --chmod=0755 docker/entrypoint-release.sh /docker-entrypoint.d/05-point-at-release.sh

EXPOSE 80 443 8081

# Probe the health listener on :8081, the one port that does not expect a PROXY
# protocol header — 80 and 443 do, since the edge (HAProxy) became the way in,
# and a wget sends none, so probing :80 would fail forever and Docker would
# call a working nginx unhealthy. The edge checks this same port; the configs
# (nginx.conf, nginx.ci.conf) both serve it. 127.0.0.1, not localhost: busybox
# wget prefers ::1 while nginx binds IPv4 only, so "localhost" is a guaranteed
# connection-refused.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8081/healthz || exit 1

# ---------------------------------------------------------------------------
# Self-contained variant for throwaway end-to-end stacks.
#
# Same runtime, but carrying its own release instead of reading one from the
# host — a CI stack has no deploy to install one, and should not be able to
# read the production release directory even by accident. FRONTEND_ROOT is what
# points the entrypoint at it, which also means the base compose file's
# /srv/frontend bind mount is simply never looked at: the overlay cannot remove
# a mount (Compose merges `volumes`), so it renders it inert instead — the same
# treatment it already gives :443 and /etc/letsencrypt.
FROM runtime AS e2e
COPY --from=release /html/ /opt/frontend-ci/html/
COPY --from=release /snippets/ /opt/frontend-ci/snippets/
COPY docker/nginx.ci.conf /opt/frontend-ci/conf.d/app.conf
ENV FRONTEND_ROOT=/opt/frontend-ci
