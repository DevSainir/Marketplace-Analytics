#!/usr/bin/env bash
# Producing the artifact: pg_dump → gzip → validity gates → age.
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

# age, to every recipient in recipients/database.txt. Two of them: an online
# key whose private half is in BACKUP_ENCRYPTION_IDENTITY on this box, and an
# offline key whose private half has never been on a server. One file, openable
# by either — which is what makes losing the box survivable, and what the old
# symmetric passphrase could not do.
encrypt_archive() {
    local plain=$1 encrypted=$2 expected stanzas

    age --encrypt --recipients-file "${BACKUP_DB_RECIPIENTS}" \
        --output "${encrypted}" "${plain}" ||
        die "age encryption failed."
    chmod 600 "${encrypted}"

    # Gate 5a — the artifact that will actually be uploaded decrypts back to a
    # valid archive. Encrypting correctly and decrypting correctly are two
    # different claims, and only the second one matters at 03:00.
    decrypt_archive "${encrypted}" | gzip -t ||
        die "Encrypted artifact does not decrypt back to a valid archive."

    # Gate 5b — and it opens for EVERY key it was meant to. 5a can only ever
    # prove the online half, because the offline half is deliberately not here.
    # Without this check a wrong character in the offline recipient would go
    # unnoticed for a year and be discovered on the one day it is all there is.
    expected=$(recipient_count "${BACKUP_DB_RECIPIENTS}")
    stanzas=$(count_recipient_stanzas "${encrypted}")
    [ "${stanzas}" -eq "${expected}" ] ||
        die "Artifact carries ${stanzas} recipient stanzas, expected ${expected} — the file and the recipient list disagree."

    log "Encryption: OK (age, ${expected} recipients, round-trip verified)."
}

# How many keys an artifact was encrypted to, read back off the file itself.
#
# age's header is ASCII at the head of the file and ends with a line starting
# `--- `. Stopping there matters: everything below it is ciphertext and could
# contain any byte sequence at all. The 16 KiB cap keeps this from ever reading
# a 100 MB "line" out of that binary if the header is malformed.
count_recipient_stanzas() {
    head -c 16384 "$1" | LC_ALL=C awk '
        /^--- / { exit }
        /^-> X25519 / { n++ }
        END { print n + 0 }
    '
}

# Opening an artifact, whichever era it came from. The EXTENSION decides, not a
# setting — the buckets hold age artifacts and, until the monthly tier rolls
# over a year after 2026-09-21, symmetric gpg ones too. Nobody restoring at
# 03:00 should have to work out which is in their hand.
#
# The identity goes in through a process substitution: it never lands on disk,
# and `ps` sees the file descriptor rather than the key.
decrypt_archive() {
    local archive=$1

    case ${archive} in
    *.age)
        [ -n "${BACKUP_ENCRYPTION_IDENTITY:-}" ] ||
            die "BACKUP_ENCRYPTION_IDENTITY is not set — cannot open ${archive##*/}."
        age --decrypt \
            --identity <(printf '%s\n' "${BACKUP_ENCRYPTION_IDENTITY}") \
            "${archive}" ||
            die "age could not decrypt ${archive##*/} with the online identity."
        ;;
    *.gpg)
        [ -n "${BACKUP_ENCRYPTION_KEY:-}" ] ||
            die "${archive##*/} predates age and BACKUP_ENCRYPTION_KEY is not set."
        gpg --batch --quiet --decrypt --passphrase-fd 3 "${archive}" \
            3< <(printf '%s' "${BACKUP_ENCRYPTION_KEY}")
        ;;
    *)
        die "Unrecognised artifact format: ${archive##*/}"
        ;;
    esac
}

sha256_of() {
    if command -v sha256sum >/dev/null; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}
