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
#
# The seed is then SHIFTED FORWARD so its newest day is today. The dump carries
# absolute dates (2026-06-30..2026-07-14 when it was taken) while every screen
# it feeds reads a window relative to now — the monitoring summary defaults to
# the last 30 days. Those two facts gave the fixture a shelf life: on
# 2026-08-14 the default window opened at 2026-07-15, one day after the seed's
# last row, so the summary came back empty, the SKU dropdown had nothing to
# filter, and the end-to-end tier went red on a change that touched none of it
# — and would have stayed red every day after. Shifting on load makes the seed
# self-ageing, which is the only version of this that does not expire again.
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
  # Re-date the seed onto today. Driven off information_schema rather than a
  # hard-coded table list so a new dated table cannot silently keep the old
  # dates and reintroduce the expiry. One shared offset keeps every table's
  # dates aligned with each other, and applying it to date PRIMARY KEY columns
  # is safe: a constant shift preserves uniqueness.
  cat <<'SQL'
DO $$
DECLARE
  rec record;
  newest date := NULL;
  candidate date;
  shift_days int;
BEGIN
  FOR rec IN
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = 'monitoring'
      AND c.data_type = 'date'
      AND t.table_type = 'BASE TABLE'
  LOOP
    EXECUTE format('SELECT max(%I) FROM monitoring.%I', rec.column_name, rec.table_name)
      INTO candidate;
    IF candidate IS NOT NULL AND (newest IS NULL OR candidate > newest) THEN
      newest := candidate;
    END IF;
  END LOOP;

  IF newest IS NULL THEN
    RAISE NOTICE 'Seed carries no dated rows; nothing to shift.';
    RETURN;
  END IF;

  shift_days := current_date - newest;
  IF shift_days <= 0 THEN
    RAISE NOTICE 'Seed already reaches %; no shift needed.', newest;
    RETURN;
  END IF;

  FOR rec IN
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = 'monitoring'
      AND c.data_type = 'date'
      AND t.table_type = 'BASE TABLE'
  LOOP
    EXECUTE format(
      'UPDATE monitoring.%I SET %I = %I + %s', rec.table_name, rec.column_name,
      rec.column_name, shift_days
    );
  END LOOP;

  RAISE NOTICE 'Shifted the seed forward % day(s); newest day is now %.',
    shift_days, current_date;
END $$;
SQL
  echo "COMMIT;"
} | docker exec -i "${CONTAINER}" psql \
      --username "${DB_USER}" --dbname "${DB_NAME}" \
      --set ON_ERROR_STOP=1 --quiet

echo "Seed loaded. Row counts:"
docker exec "${CONTAINER}" psql --username "${DB_USER}" --dbname "${DB_NAME}" --command \
  "SELECT relname, n_live_tup FROM pg_stat_user_tables
   WHERE schemaname = 'monitoring' ORDER BY relname;"
