#!/usr/bin/env bash
# Dump the local dev database's monitoring data into a portable seed file.
#
# Run from the repo (any directory) on the DEV machine where the docker-compose
# postgres holds the harvested history:
#
#   backend/scripts/dump_seed.sh
#
# Produces backend/seed/monitoring_seed.sql.gz — data-only COPY statements for
# the whole `monitoring` schema (facts + dimensions + saved matrix edits),
# gzipped (the raw dump is a few MB; compressed it stays small).
# The auth schema is deliberately NOT dumped: register accounts on the target
# host with the invite code instead of copying dev credentials around.
#
# Re-run any time to refresh the seed (e.g. after a harvest).
set -euo pipefail

# Derived from the compose project, like load_seed.sh's — a bare container name
# aimed the loader at production once (see load_seed.sh), and the direction
# this script runs in is the other half of that mistake: pointed at a live
# stack it would write real sellers' catalogue data into a seed file meant to
# be shared.
PROJECT="${COMPOSE_PROJECT_NAME:-marketplace-service}"
CONTAINER="${SEED_PG_CONTAINER:-${PROJECT}-postgres-1}"
DB_USER="${POSTGRES_USER:-marketplace}"
DB_NAME="${POSTGRES_DB:-marketplace}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${SCRIPT_DIR}/../seed"
OUT_FILE="${OUT_DIR}/monitoring_seed.sql.gz"

mkdir -p "${OUT_DIR}"

docker exec "${CONTAINER}" pg_dump \
  --username "${DB_USER}" \
  --dbname "${DB_NAME}" \
  --schema=monitoring \
  --data-only \
  --no-owner \
  --no-privileges \
  | gzip -9 > "${OUT_FILE}"

TABLES=$(gzip -dc "${OUT_FILE}" | grep -c '^COPY ' || true)
echo "Wrote ${OUT_FILE} ($(du -h "${OUT_FILE}" | cut -f1), ${TABLES} tables)."
