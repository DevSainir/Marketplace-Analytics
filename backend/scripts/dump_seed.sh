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
# gzipped (the raw dump is a few MB; compressed it stays small enough to commit).
# The auth schema is deliberately NOT dumped: register accounts on the target
# host with the invite code instead of copying dev credentials around.
#
# Re-run any time to refresh the seed (e.g. after a harvest).
set -euo pipefail

CONTAINER="${SEED_PG_CONTAINER:-marketplace-service-postgres-1}"
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
