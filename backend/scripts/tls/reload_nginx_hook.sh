#!/usr/bin/env bash
# certbot DEPLOY HOOK: make nginx re-read a certificate that has just been
# renewed. Installed to /etc/letsencrypt/renewal-hooks/deploy/ by
# issue_certificate.sh; certbot runs everything in that directory after a
# successful renewal, and only after one.
#
# WHY THIS IS NOT OPTIONAL.
#
# nginx reads its certificate ONCE, at start or reload, and then serves what it
# holds in memory. certbot renews on the HOST; the frontend container has
# /etc/letsencrypt bind-mounted read-only, so it sees the new files immediately
# and keeps serving the old certificate regardless — until something restarts
# it. Nothing does, on its own.
#
# So the failure is slow and silent, which is the shape this deployment has
# already been bitten by once (see issue_certificate.sh): renewal succeeds and
# reports success, the files on disk are correct, every check of the CERTIFICATE
# passes — and the certificate on the WIRE is the old one, quietly counting down
# to the expiry that renewal was supposed to prevent. Frequent deploys mask it,
# because each one restarts the container and picks up the current file. That
# masking is the danger: it means the gap shows up during a quiet period, which
# is exactly when nobody is watching.
#
# `nginx -s reload` is a graceful signal to the master process. Workers finish
# the requests they are serving and are replaced; no connection is dropped and
# there is no window in which the site is down.
set -euo pipefail

CONTAINER=marketplace-service-frontend-1

if ! command -v docker >/dev/null; then
  echo "[tls-hook] docker not on PATH; cannot reload nginx." >&2
  exit 1
fi

# The stack being down is not an error worth failing a renewal over: whenever it
# comes back up, nginx reads the current certificate from the mount anyway. This
# is the ONE case that is genuinely fine, so it is the one case that exits 0.
if [ -z "$(docker ps -q -f "name=^${CONTAINER}$" 2>/dev/null)" ]; then
  echo "[tls-hook] ${CONTAINER} is not running; it will read the new certificate when it starts."
  exit 0
fi

# Validate before reloading. A reload against a broken config leaves the OLD
# workers running, so the site survives — but it also means the reload silently
# did nothing, which is the failure this hook exists to prevent.
if ! docker exec "$CONTAINER" nginx -t; then
  echo "[tls-hook] nginx config test FAILED; refusing to reload. Certificate renewed but NOT served." >&2
  exit 1
fi

docker exec "$CONTAINER" nginx -s reload
echo "[tls-hook] nginx reloaded; now serving the renewed certificate."
