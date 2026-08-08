#!/usr/bin/env bash
# The weekly deep check: prove the artifact restores, by restoring it.
#
# Every other gate in this job checks a property of the file. This one checks
# the only property anyone actually cares about — that a Postgres will accept
# it — and it checks it on the ENCRYPTED artifact, decrypting exactly the bytes
# that get uploaded. gzip said OK, gpg said OK and psql said no is a real
# outcome, and finding it out on a Sunday night beats finding it out during an
# incident.
#
# The rehearsal happens in a scratch container on --network none: it can never
# reach the live stack, and it is capped in memory and CPU so it cannot starve
# the running services on a 3.8 GB VPS.

RESTORE_CONTAINER="marketplace-backup-restore-check"

# The scratch server's data directory is a NAMED volume, and it is named for a
# reason. postgres:16-alpine declares `VOLUME /var/lib/postgresql/data`, so
# every plain `docker run` mints an anonymous volume that `docker rm -f` leaves
# behind — the rehearsal would quietly abandon ~1.2 GB every Sunday, and this
# VPS has previously gone read-only, taking the whole site down, from exactly
# that kind of slow disk leak. A fixed name bounds the damage at one volume no
# matter how the run dies, and cleanup removes it at both ends of the check.
RESTORE_VOLUME="marketplace-backup-restore-data"

# GNU coreutils' `timeout`, when the host has it. The VPS does; a developer's
# Mac does not, and a missing wall-clock guard is no reason for the rehearsal
# to be unrunnable on a laptop.
with_timeout() {
    local seconds=$1
    shift
    if command -v timeout >/dev/null; then
        timeout "${seconds}" "$@"
    else
        "$@"
    fi
}

restore_check_cleanup() {
    # -v so the data directory goes with the container, and an explicit volume
    # rm for the case where the container is already gone but the volume is not.
    docker rm -f -v "${RESTORE_CONTAINER}" >/dev/null 2>&1 || true
    docker volume rm -f "${RESTORE_VOLUME}" >/dev/null 2>&1 || true
}

# schema.table for every table that currently holds at least one row. "Has
# rows" does not race with a concurrent harvest the way an exact count does,
# so it is a check that never produces a false alarm at 03:00.
source_nonempty_tables() {
    pg_client psql \
        -h "${BACKUP_PG_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -tAq -c "$(nonempty_tables_sql)"
}

nonempty_tables_sql() {
    cat <<'SQL'
SELECT t.table_schema || '.' || t.table_name
  FROM information_schema.tables AS t
 WHERE t.table_type = 'BASE TABLE'
   AND t.table_schema NOT IN ('pg_catalog', 'information_schema')
   AND (xpath(
          '/row/c/text()',
          query_to_xml(
              format('SELECT count(*) AS c FROM %I.%I', t.table_schema, t.table_name),
              false, true, ''
          )
       ))[1]::text::bigint > 0
 ORDER BY 1;
SQL
}

# Restores `archive` into a throwaway Postgres and asserts it came back whole.
# `expected_tables` and `expected_nonempty` are the inventories captured from
# the live database at dump time.
run_restore_check() {
    local archive=$1 expected_tables=$2 expected_nonempty=$3
    local started restored_tables restored_nonempty missing total

    # No local trap: backup.sh installs a single EXIT trap that tears this
    # container down on every path out, including `die`.
    restore_check_cleanup

    log "Deep check: starting a scratch PostgreSQL (${BACKUP_RESTORE_MEM}, ${BACKUP_RESTORE_CPUS} CPU) …"
    docker run -d \
        --name "${RESTORE_CONTAINER}" \
        --network none \
        --memory "${BACKUP_RESTORE_MEM}" \
        --cpus "${BACKUP_RESTORE_CPUS}" \
        -v "${RESTORE_VOLUME}:/var/lib/postgresql/data" \
        -e POSTGRES_USER="${POSTGRES_USER}" \
        -e POSTGRES_DB="${POSTGRES_DB}" \
        -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
        "${BACKUP_PG_IMAGE}" \
        -c fsync=off -c full_page_writes=off -c synchronous_commit=off \
        >/dev/null || die "Could not start the restore-check container."

    started=$(date +%s)
    until docker exec "${RESTORE_CONTAINER}" \
        pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
        [ $(($(date +%s) - started)) -lt 120 ] ||
            die "Restore-check PostgreSQL did not become ready within 120s."
        sleep 2
    done

    log "Deep check: restoring the encrypted artifact …"
    started=$(date +%s)
    if ! decrypt_archive "${archive}" | gzip -dc |
        with_timeout "${BACKUP_RESTORE_TIMEOUT_SECONDS}" \
            docker exec -i "${RESTORE_CONTAINER}" \
            psql --quiet -v ON_ERROR_STOP=1 \
            -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null; then
        die "Restoring the dump into a clean PostgreSQL failed (psql/ON_ERROR_STOP)."
    fi
    log "Deep check: restore completed in $(($(date +%s) - started))s."

    # Structure: the restored copy must hold exactly the tables the source had.
    restored_tables=$(docker exec "${RESTORE_CONTAINER}" psql -tAq \
        -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -c "SELECT schemaname || '.' || tablename FROM pg_tables
             WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
             ORDER BY 1;")

    missing=$(comm -23 \
        <(printf '%s\n' "${expected_tables}" | sort) \
        <(printf '%s\n' "${restored_tables}" | sort))
    [ -z "${missing}" ] ||
        die "Restored database is missing tables: $(printf '%s' "${missing}" | tr '\n' ' ')"
    log "Deep check: $(printf '%s\n' "${restored_tables}" | grep -c .) tables present, matching the source."

    # Content: every table that had rows at dump time must have rows now.
    # This is what catches a dump whose schema is perfect and whose COPY blocks
    # never made it.
    restored_nonempty=$(docker exec "${RESTORE_CONTAINER}" psql -tAq \
        -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "$(nonempty_tables_sql)")

    missing=$(comm -23 \
        <(printf '%s\n' "${expected_nonempty}" | sort) \
        <(printf '%s\n' "${restored_nonempty}" | sort))
    [ -z "${missing}" ] ||
        die "Restored tables came back empty: $(printf '%s' "${missing}" | tr '\n' ' ')"

    total=$(docker exec "${RESTORE_CONTAINER}" psql -tAq \
        -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -c "SELECT coalesce(sum(n_live_tup), 0) FROM pg_stat_user_tables;")
    log "Deep check: $(printf '%s\n' "${expected_nonempty}" | grep -c .) populated tables, ~${total} rows restored."

    # The migration pointer: a dump that restores but lands on an older
    # alembic revision than the running stack would fail on first boot.
    local revision
    revision=$(docker exec "${RESTORE_CONTAINER}" psql -tAq \
        -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -c "SELECT version_num FROM public.alembic_version;" 2>/dev/null || true)
    [ -n "${revision}" ] ||
        die "Restored database has no alembic_version row."
    log "Deep check: alembic revision ${revision}."

    log "Deep check PASSED — this artifact restores into an empty PostgreSQL."
    restore_check_cleanup
}
