#!/usr/bin/env bash
# Load backend/seed/monitoring_seed.sql into the compose postgres.
#
# Run on the TARGET host (e.g. a deployed one) AFTER the stack is up — the migrate
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

die() {
  echo "$*" >&2
  exit 1
}

# WHICH DATABASE THIS EMPTIES, and why the default is no longer a bare name.
#
# On 2026-09-10 this script truncated production's `monitoring` schema. The
# nightly end-to-end tier runs on the production host's own runner and isolates
# its stack through Compose — a separate project, separate ports, and a guard
# step that refuses to start if either is lost. This script bypasses Compose
# entirely: it reaches for a container BY NAME, and the name it defaulted to
# was production's. Every Compose-level guard held, and the seed still landed
# on the live database.
#
# So the target is derived from the compose project instead: the e2e tier
# exports COMPOSE_PROJECT_NAME=marketplace-analytic-e2e, which now names its own
# postgres rather than production's.
PROJECT="${COMPOSE_PROJECT_NAME:-marketplace-analytic}"
CONTAINER="${SEED_PG_CONTAINER:-${PROJECT}-postgres-1}"
DB_USER="${POSTGRES_USER:-marketplace}"
DB_NAME="${POSTGRES_DB:-marketplace}"

# The backstop for everything the derivation above does not catch — a hand-run
# `SEED_PG_CONTAINER=…`, a future caller with its own idea of the name, a
# developer on the production box. The marker is read from the TARGET's own
# stack, never from this checkout's backend/.env: on the runner that file is a
# copy of .env.example and says `local` while the container being addressed is
# production's. That is precisely the lie that has to be caught here.
assert_target_is_not_production() {
  local project api environment

  project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' \
    "${CONTAINER}" 2>/dev/null) ||
    die "Cannot inspect ${CONTAINER}. Is the stack up?"

  api=$(docker ps --quiet \
    --filter "label=com.docker.compose.project=${project}" \
    --filter "label=com.docker.compose.service=api" | head -n 1)
  [[ -n "${api}" ]] ||
    die "No running api container in project '${project}', so the environment of
${CONTAINER} cannot be established. Refusing to truncate a database this script
cannot identify. Start the stack, or set
SEED_TARGET_IS_NOT_PRODUCTION=i-am-sure to override."

  environment=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${api}" |
    sed -n 's/^ENVIRONMENT=//p' | head -n 1)

  echo "Seeding ${CONTAINER} — compose project '${project}', ENVIRONMENT=${environment:-unset}."

  if [[ "${environment}" == "production" ]]; then
    die "REFUSING: ${CONTAINER} belongs to a stack running ENVIRONMENT=production.
This script TRUNCATEs every table in the monitoring schema. It has emptied
production once already (2026-09-10); it does not get to do it twice."
  fi

  [[ -n "${environment}" ]] ||
    die "The api container of project '${project}' declares no ENVIRONMENT.
Refusing to truncate a database this script cannot identify. Set
SEED_TARGET_IS_NOT_PRODUCTION=i-am-sure to override."
}

if [[ "${SEED_TARGET_IS_NOT_PRODUCTION:-}" == "i-am-sure" ]]; then
  echo "WARNING: environment check skipped by request; seeding ${CONTAINER}."
else
  assert_target_is_not_production
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_FILE="${SCRIPT_DIR}/../seed/monitoring_seed.sql.gz"

if [[ ! -f "${SEED_FILE}" ]]; then
  die "Seed file not found: ${SEED_FILE}"
fi

{
  echo "BEGIN;"
  # Name the session in the truncate guard's audit row, and take the opt-in the
  # guard requires: emptying these tables is this script's whole job, while any
  # OTHER session doing it is the incident the guard exists to stop. Both are
  # LOCAL, so they last exactly as long as this transaction.
  echo "SET LOCAL application_name = 'load_seed.sh';"
  echo "SET LOCAL app.allow_truncate = 'on';"
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
