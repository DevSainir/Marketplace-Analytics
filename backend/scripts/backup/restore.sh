#!/usr/bin/env bash
# The other half of a backup system: getting the data back.
#
#   restore.sh list [hoster|cloudfare] [daily|weekly|monthly]
#   restore.sh fetch <hoster|cloudfare> <tier/objectname> [outdir]
#   restore.sh load  <file.sql.gz.age | .sql.gz.gpg | .sql.gz> <container>
#
# `list` and `fetch` are read-only and safe to run any time. `load` DESTROYS
# the target database and asks before it does. It refuses the live production
# container outright: recovering into the running stack is a decision that
# deserves a human typing the command themselves, with the stack stopped.
#
# Everything here uses the same pinned aws-cli image and the same credentials
# from backend/.env as backup.sh — there is nothing extra to install on a host
# where you are already having a bad day.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=lib/log.sh
. "${SCRIPT_DIR}/lib/log.sh"
# shellcheck source=lib/config.sh
. "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/dump.sh
. "${SCRIPT_DIR}/lib/dump.sh"
# shellcheck source=lib/upload.sh
. "${SCRIPT_DIR}/lib/upload.sh"

PROTECTED_CONTAINER="${BACKUP_PROTECTED_CONTAINER:-marketplace-analytics-postgres-1}"

usage() {
    sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

load_env_file "${BACKUP_ENV_FILE:-${BACKEND_DIR}/.env}"
apply_backup_defaults

cmd_list() {
    local dest=${1:-} tier=${2:-} bucket
    local -a destinations=("${BACKUP_DESTINATIONS[@]}")
    [ -n "${dest}" ] && destinations=("${dest}")

    for dest in "${destinations[@]}"; do
        bucket=$(dest_var "${dest}" bucket) || die "Unknown destination: ${dest}"
        echo "--- ${dest} (s3://${bucket}) ---"
        run_aws "${dest}" s3 ls "s3://${bucket}/${tier:+${tier}/}" --recursive ||
            warn "Could not list ${dest}."
    done
}

cmd_fetch() {
    local dest=${1:?destination required} key=${2:?object key required}
    local outdir=${3:-${BACKUP_ARTIFACT_DIR}}
    local bucket filename expected actual recorded

    bucket=$(dest_var "${dest}" bucket) || die "Unknown destination: ${dest}"
    filename=${key##*/}
    mkdir -p "${outdir}"

    # aws-cli only ever sees the mounted directory, so download into it and
    # move afterwards rather than teaching the container about arbitrary paths.
    BACKUP_ARTIFACT_DIR="${outdir}" BACKUP_AWS_MOUNT_MODE=rw \
        run_aws "${dest}" s3 cp \
        "s3://${bucket}/${key}" "/data/${filename}" --only-show-errors ||
        die "Download of ${dest}:${key} failed."

    expected=$(BACKUP_ARTIFACT_DIR="${outdir}" run_aws "${dest}" s3api head-object \
        --bucket "${bucket}" --key "${key}" \
        --query 'Metadata.sha256' --output text 2>/dev/null | tr -d '[:space:]')
    actual=$(sha256_of "${outdir}/${filename}")

    if [ -n "${expected}" ] && [ "${expected}" != "None" ] && [ "${expected}" != "${actual}" ]; then
        die "Checksum mismatch on ${filename}: object says ${expected}, file is ${actual}."
    fi
    # The check above proves the download matches what the bucket says it
    # should be — and both were written by the same credentials, so it says
    # nothing about who put them there. Artifacts are encrypted to a public
    # key, so a forged one decrypts and restores perfectly. The ledger this box
    # kept when it wrote the artifact is the record those credentials cannot
    # reach.
    recorded=$(recorded_artifact_sha "${filename}")
    if [ -z "${recorded}" ]; then
        warn "No local record of ${filename} — either this box did not write it, or the state directory is gone. Compare against the checksum in the weekly Telegram report before restoring."
    elif [ "${recorded}" != "${actual}" ]; then
        die "${filename} is NOT what this box uploaded: recorded ${recorded}, downloaded ${actual}. Treat the object as tampered with and do not restore it."
    else
        log "Provenance: matches the checksum recorded when this artifact was written."
    fi

    log "Downloaded ${outdir}/${filename} ($(human_bytes "$(file_size "${outdir}/${filename}")"), checksum verified)."

    if [ -n "${BACKUP_DECRYPT_TO_PLAIN:-}" ]; then
        # %.* rather than %.gpg: the suffix is .age now and .gpg on anything
        # older, and decrypt_archive tells them apart on its own.
        decrypt_archive "${outdir}/${filename}" >"${outdir}/${filename%.*}"
        log "Decrypted to ${outdir}/${filename%.*}."
    fi
}

cmd_load() {
    local archive=${1:?archive required} container=${2:?target container required}
    local reply

    [ -r "${archive}" ] || die "Not readable: ${archive}"
    docker inspect "${container}" >/dev/null 2>&1 ||
        die "No such container: ${container}"

    if [ "${container}" = "${PROTECTED_CONTAINER}" ] &&
        [ "${BACKUP_ALLOW_PRODUCTION_RESTORE:-0}" != "1" ]; then
        die "Refusing to restore into the live container ${container}.
Stop the stack first, then re-run with BACKUP_ALLOW_PRODUCTION_RESTORE=1."
    fi

    echo "This DROPS and recreates '${POSTGRES_DB}' inside ${container}."
    echo "Everything currently in that database is lost."
    read -r -p "Type the database name to confirm: " reply
    [ "${reply}" = "${POSTGRES_DB}" ] || die "Not confirmed."

    log "Recreating ${POSTGRES_DB} in ${container} …"
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${container}" \
        psql -U "${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 \
        -c "DROP DATABASE IF EXISTS ${POSTGRES_DB} WITH (FORCE);" \
        -c "CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};" ||
        die "Could not recreate the target database."

    log "Restoring ${archive##*/} …"
    case ${archive} in
    *.age | *.gpg) decrypt_archive "${archive}" ;;
    *) cat "${archive}" ;;
    esac | gzip -dc |
        docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" "${container}" \
            psql --quiet -v ON_ERROR_STOP=1 \
            -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null ||
        die "Restore failed."

    log "Restore complete. Start the stack and let alembic confirm the revision."
}

case ${1:-} in
list)
    shift
    cmd_list "$@"
    ;;
fetch)
    shift
    cmd_fetch "$@"
    ;;
load)
    shift
    cmd_load "$@"
    ;;
-h | --help | '') usage 0 ;;
*)
    echo "Unknown command: $1" >&2
    usage 2
    ;;
esac
