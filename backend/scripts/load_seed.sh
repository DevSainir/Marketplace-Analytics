#!/usr/bin/env bash
# Load backend/seed/monitoring_seed.sql into the compose postgres.
#
# Run on the TARGET host (e.g. the VPS) AFTER the stack is up — the migrate
# service must have applied the schema first:
#
#   make up
#   backend/scripts/load_seed.sh
#
# Idempotent: the monitoring tables are TRUNCATED before loading, so re-running
# replaces the seeded data instead of duplicating it. The whole load runs in a
# single transaction — it either fully applies or leaves the database untouched.
set -euo pipefail

CONTAINER="${SEED_PG_CONTAINER:-marketplace-service-postgres-1}"
DB_USER="${POSTGRES_USER:-marketplace}"
DB_NAME="${POSTGRES_DB:-marketplace}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_FILE="${SCRIPT_DIR}/../seed/monitoring_seed.sql.gz"

if [[ ! -f "${SEED_FILE}" ]]; then
  echo "Seed file not found: ${SEED_FILE}" >&2
  exit 1
fi

{
  echo "BEGIN;"
  # Empty every monitoring table first so the load is repeatable.
  docker exec "${CONTAINER}" psql \
    --username "${DB_USER}" --dbname "${DB_NAME}" --tuples-only --no-align \
    --command "SELECT format('TRUNCATE TABLE %I.%I CASCADE;', schemaname, tablename)
               FROM pg_tables WHERE schemaname = 'monitoring';"
  gzip -dc "${SEED_FILE}"
  echo "COMMIT;"
} | docker exec -i "${CONTAINER}" psql \
      --username "${DB_USER}" --dbname "${DB_NAME}" \
      --set ON_ERROR_STOP=1 --quiet

echo "Seed loaded. Row counts:"
docker exec "${CONTAINER}" psql --username "${DB_USER}" --dbname "${DB_NAME}" --command \
  "SELECT relname, n_live_tup FROM pg_stat_user_tables
   WHERE schemaname = 'monitoring' ORDER BY relname;"
