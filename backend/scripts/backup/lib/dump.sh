#!/usr/bin/env bash
# Producing the artifact: pg_dump → gzip → validity gates → gpg.
#
# The dump is plain SQL rather than pg_dump's custom format on purpose. It is
# restorable by any `psql` of any vintage without a matching pg_restore, it
# ends in a marker line that proves the dump ran to completion, and it is the
# same shape as backend/scripts/dump_seed.sh — one restore procedure to learn,
# not two. At 751 MB the single-threaded restore costs minutes, not hours.

# Runs a one-shot Postgres container on the stack's network. Used both for
# pg_dump and for the psql probes; the image is the one the stack already
# runs, so the client version always matches the server.
pg_client() {
    PGPASSWORD="${POSTGRES_PASSWORD}" docker run --rm \
        --network "${BACKUP_DOCKER_NETWORK}" \
        -e PGPASSWORD \
        "${BACKUP_PG_IMAGE}" "$@"
}

# One line per table, `schema.table`. Captured from the live database at dump
# time and compared against the restored copy on Sunday: structure does not
# race with a concurrent harvest the way row counts do, so this is an exact
# equality check rather than a fuzzy one.
source_table_inventory() {
    pg_client psql \
        -h "${BACKUP_PG_HOST}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        -tAq -c "SELECT schemaname || '.' || tablename
                   FROM pg_tables
                  WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                  ORDER BY 1;"
}

# pg_dump | gzip, with both exit codes checked. A naive pipeline reports only
# gzip's status, so a pg_dump that died halfway would look like a success and
# leave a perfectly valid gzip file holding half a database.
create_dump() {
    local target=$1
    local -a status

    log "Dumping ${POSTGRES_DB} from ${BACKUP_PG_HOST} …"
    set +e
    pg_client pg_dump \
        -h "${BACKUP_PG_HOST}" \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        --format=plain \
        --no-owner \
        --no-privileges |
        gzip -9 >"${target}"
    status=("${PIPESTATUS[@]}")
    set -e

    [ "${status[0]}" -eq 0 ] || die "pg_dump exited ${status[0]}."
    [ "${status[1]}" -eq 0 ] || die "gzip exited ${status[1]}."
    chmod 600 "${target}"
    log "Dump written: $(human_bytes "$(file_size "${target}")")."
}

file_size() {
    # Linux coreutils on the VPS, BSD stat on a developer's Mac.
    stat -c %s "$1" 2>/dev/null || stat -f %z "$1"
}

# The three validity gates the compressed dump has to pass before anything is
# encrypted or uploaded.
verify_archive() {
    local archive=$1
    local size previous floor

    # 1. Archive integrity — every gzip block decompresses and the CRC matches.
    gzip -t "${archive}" || die "gzip integrity check failed on ${archive}."
    log "Archive integrity: OK (gzip -t)."

    # 2. Completeness — pg_dump's own end-of-dump marker. This is what
    #    distinguishes a finished dump from a stream that was cut short but
    #    still gzipped cleanly.
    if ! gzip -dc "${archive}" | tail -c 4096 |
        grep -q 'PostgreSQL database dump complete'; then
        die "Dump has no completion marker — pg_dump did not finish."
    fi
    log "Completion marker: OK."

    # 3. Size — an absolute floor, plus a comparison against the last good run.
    #    The floor catches an empty database; the comparison catches the more
    #    realistic case of a dump that lost most of its rows and is still
    #    comfortably above any fixed threshold.
    size=$(file_size "${archive}")
    [ "${size}" -ge "${BACKUP_MIN_BYTES}" ] ||
        die "Dump is $(human_bytes "${size}"), below the ${BACKUP_MIN_BYTES}-byte floor."

    previous=$(cat "${BACKUP_STATE_DIR}/last-size" 2>/dev/null || echo 0)
    if [ "${previous}" -gt 0 ]; then
        floor=$((previous * BACKUP_SHRINK_PCT / 100))
        [ "${size}" -ge "${floor}" ] ||
            die "Dump shrank to $(human_bytes "${size}") from $(human_bytes "${previous}") — under ${BACKUP_SHRINK_PCT}% of the last run."
        log "Size: $(human_bytes "${size}") (previous $(human_bytes "${previous}"))."
    else
        log "Size: $(human_bytes "${size}") (no previous run to compare against)."
    fi

    printf '%s' "${size}" >"${BACKUP_STATE_DIR}/last-size"
}

# Symmetric AES-256. --compress-algo none because the input is already gzipped
# and gpg's own compression would only burn CPU. The passphrase goes in via a
# file descriptor, never argv, so it never appears in `ps`.
encrypt_archive() {
    local plain=$1 encrypted=$2

    gpg --batch --yes --quiet \
        --symmetric \
        --cipher-algo AES256 \
        --compress-algo none \
        --passphrase-fd 3 \
        --output "${encrypted}" \
        "${plain}" 3< <(printf '%s' "${BACKUP_ENCRYPTION_KEY}") ||
        die "gpg encryption failed."
    chmod 600 "${encrypted}"

    # Round-trip the artifact that will actually be uploaded. Encrypting
    # correctly and decrypting correctly are two different claims, and only the
    # second one matters at 03:00 on the night something has gone wrong.
    decrypt_archive "${encrypted}" | gzip -t ||
        die "Encrypted artifact does not decrypt back to a valid archive."
    log "Encryption: OK (AES256, round-trip verified)."
}

decrypt_archive() {
    gpg --batch --quiet --decrypt --passphrase-fd 3 "$1" \
        3< <(printf '%s' "${BACKUP_ENCRYPTION_KEY}")
}

sha256_of() {
    if command -v sha256sum >/dev/null; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}
