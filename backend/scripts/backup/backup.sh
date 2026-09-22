#!/usr/bin/env bash
# Nightly PostgreSQL backup: dump → verify → encrypt → (Sunday) restore
# rehearsal → push to Cloudflare R2 and Hoster S3.
#
#   backend/scripts/backup/backup.sh [--tiers daily,weekly,monthly]
#                                    [--force-deep-check]
#                                    [--env-file PATH]
#
# Installed by backend/scripts/backup/cron/marketplace-backup, which fires it
# at 00:00 UTC = 03:00 Europe/Moscow. Moscow has had no DST since 2014, so the
# UTC entry and the Moscow wall clock never drift apart.
#
# WHICH TIERS GET A COPY. Every run writes daily/. Sunday also writes weekly/,
# the 1st of the month also writes monthly/ — so a Sunday-the-1st writes all
# three. The date that decides this is the Moscow date, matching the schedule.
# Retention is NOT this script's job: lifecycle policies on the buckets
# themselves expire daily/ after 7 days, weekly/ after 30 and monthly/ after
# 365. A script that deletes and a bucket that deletes is one rule too many.
#
# WHAT "VALID" MEANS HERE, in the order the gates run:
#   1. pg_dump AND gzip both exited 0        (PIPESTATUS, not just the tail)
#   2. gzip -t decompresses the whole file   (archive integrity)
#   3. the dump carries pg_dump's own end-of-dump marker  (completeness)
#   4. the file clears an absolute floor and did not shrink against last run
#   5a. the encrypted artifact decrypts back to a valid archive (round trip)
#   5b. it carries one recipient stanza per recipient, so the offline key —
#       which cannot be tested here, being offline — really is on the file
#   6. on Sunday: it restores into a scratch PostgreSQL, with the same tables
#      the source had and rows in every table that had rows
# Only then is anything uploaded, and each uploaded object is read back and
# checked against the local size and SHA-256.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=lib/log.sh
. "${SCRIPT_DIR}/lib/log.sh"
# shellcheck source=lib/config.sh
. "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/dump.sh
. "${SCRIPT_DIR}/lib/dump.sh"
# shellcheck source=lib/verify_restore.sh
. "${SCRIPT_DIR}/lib/verify_restore.sh"
# shellcheck source=lib/upload.sh
. "${SCRIPT_DIR}/lib/upload.sh"
# shellcheck source=lib/secrets.sh
. "${SCRIPT_DIR}/lib/secrets.sh"

ENV_FILE="${BACKUP_ENV_FILE:-${BACKEND_DIR}/.env}"
TIER_OVERRIDE=""
PLAIN_ARCHIVE=""

while [ $# -gt 0 ]; do
    case $1 in
    --tiers)
        TIER_OVERRIDE=$2
        shift 2
        ;;
    --force-deep-check)
        BACKUP_FORCE_DEEP_CHECK=1
        shift
        ;;
    --no-upload)
        # Everything except the push: for exercising the gates on a machine
        # that should not be writing into the production buckets.
        BACKUP_SKIP_UPLOAD=1
        shift
        ;;
    --env-file)
        ENV_FILE=$2
        shift 2
        ;;
    -h | --help)
        sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    *)
        echo "Unknown argument: $1" >&2
        exit 2
        ;;
    esac
done

cleanup() {
    # The plaintext dump is the one artifact that must never outlive the run.
    [ -n "${PLAIN_ARCHIVE}" ] && rm -f "${PLAIN_ARCHIVE}"
    restore_check_cleanup
    return 0
}
trap cleanup EXIT

load_env_file "${ENV_FILE}"
apply_backup_defaults

mkdir -p "${BACKUP_ARTIFACT_DIR}" "${BACKUP_STATE_DIR}" "${BACKUP_LOG_DIR}"
chmod 700 "${BACKUP_WORK_DIR}" "${BACKUP_ARTIFACT_DIR}" "${BACKUP_STATE_DIR}"
log_init "${BACKUP_LOG_DIR}/backup-$(TZ="${BACKUP_TZ}" date +%Y%m%d).log"

# One run at a time. An overlapping run means the previous one has been going
# for over 24 hours, which is itself the incident.
if command -v flock >/dev/null; then
    exec 9>"${BACKUP_WORK_DIR}/.lock"
    flock -n 9 ||
        die "Another backup run still holds the lock — the previous run never finished."
else
    warn "flock is unavailable; concurrent runs are not prevented."
fi

require_config

# --- What kind of night is this? -------------------------------------------
DOW=$(TZ="${BACKUP_TZ}" date +%u)  # 1 = Monday … 7 = Sunday
DOM=$(TZ="${BACKUP_TZ}" date +%-d) # no leading zero, so it compares as a number
STAMP=$(TZ="${BACKUP_TZ}" date +%Y%m%dT%H%M%S)

TIERS=(daily)
[ "${DOW}" -eq "${BACKUP_WEEKLY_DOW}" ] && TIERS+=(weekly)
[ "${DOM}" -eq 1 ] && TIERS+=(monthly)

if [ -n "${TIER_OVERRIDE}" ]; then
    IFS=',' read -r -a TIERS <<<"${TIER_OVERRIDE}"
    log "Tier override in effect: ${TIERS[*]}"
fi

DEEP_CHECK=0
if [ "${DOW}" -eq "${BACKUP_DEEP_CHECK_DOW}" ] || [ "${BACKUP_FORCE_DEEP_CHECK}" = "1" ]; then
    DEEP_CHECK=1
fi

BASENAME="marketplace-${STAMP}msk.sql.gz"
PLAIN_ARCHIVE="${BACKUP_ARTIFACT_DIR}/${BASENAME}"
ENCRYPTED_NAME="${BASENAME}.age"
ENCRYPTED_ARCHIVE="${BACKUP_ARTIFACT_DIR}/${ENCRYPTED_NAME}"

log "=== Backup run ${STAMP} MSK — tiers: ${TIERS[*]}, deep check: $([ "${DEEP_CHECK}" -eq 1 ] && echo yes || echo no) ==="

# --- Inventory, captured from the live database at dump time ---------------
SOURCE_TABLES=$(source_table_inventory) ||
    die "Could not read the table inventory from the live database."
log "Source database holds $(printf '%s\n' "${SOURCE_TABLES}" | grep -c .) tables."

SOURCE_NONEMPTY=""
if [ "${DEEP_CHECK}" -eq 1 ]; then
    SOURCE_NONEMPTY=$(source_nonempty_tables) ||
        die "Could not read the populated-table inventory from the live database."
    log "Source database has $(printf '%s\n' "${SOURCE_NONEMPTY}" | grep -c .) populated tables."
fi

# --- Dump, verify, encrypt --------------------------------------------------
create_dump "${PLAIN_ARCHIVE}"
verify_archive "${PLAIN_ARCHIVE}"
encrypt_archive "${PLAIN_ARCHIVE}" "${ENCRYPTED_ARCHIVE}"

rm -f "${PLAIN_ARCHIVE}"
PLAIN_ARCHIVE=""

ENCRYPTED_SIZE=$(file_size "${ENCRYPTED_ARCHIVE}")
ENCRYPTED_SHA=$(sha256_of "${ENCRYPTED_ARCHIVE}")
log "Artifact ${ENCRYPTED_NAME}: $(human_bytes "${ENCRYPTED_SIZE}"), sha256 ${ENCRYPTED_SHA}."
record_artifact_sha "${ENCRYPTED_NAME}" "${ENCRYPTED_SHA}"

# --- Weekly rehearsal, before anything is pushed ----------------------------
if [ "${DEEP_CHECK}" -eq 1 ]; then
    run_restore_check "${ENCRYPTED_ARCHIVE}" "${SOURCE_TABLES}" "${SOURCE_NONEMPTY}"
else
    log "Deep check skipped (runs on day ${BACKUP_DEEP_CHECK_DOW} of the week)."
fi

# --- Push -------------------------------------------------------------------
if [ "${BACKUP_SKIP_UPLOAD:-0}" = "1" ]; then
    warn "--no-upload: nothing was pushed to ${BACKUP_DESTINATIONS[*]}."
else
    upload_all "${ENCRYPTED_NAME}" "${ENCRYPTED_SHA}" "${ENCRYPTED_SIZE}" "${TIERS[@]}"
fi

# --- Local housekeeping -----------------------------------------------------
# Recent artifacts are kept on the VPS so a same-week restore does not need a
# download; the buckets remain the actual backup.
# Both extensions, deliberately. Sweeping only `.age` would leave every
# pre-2026-09-21 `.gpg` artifact on the disk for ever, and this VPS has gone
# read-only from a slow disk leak before (see lib/verify_restore.sh).
{ ls -1t "${BACKUP_ARTIFACT_DIR}"/marketplace-*.sql.gz.age \
    "${BACKUP_ARTIFACT_DIR}"/marketplace-*.sql.gz.gpg 2>/dev/null || true; } |
    tail -n "+$((BACKUP_LOCAL_KEEP + 1))" | while read -r stale; do
    log "Removing local artifact ${stale##*/}"
    rm -f "${stale}"
done

find "${BACKUP_LOG_DIR}" -maxdepth 1 -name 'backup-*.log' \
    -mtime "+${BACKUP_LOG_KEEP_DAYS}" -delete 2>/dev/null || true

# The secrets bundle is a manual job, and the way it fails is silence: an
# operator rotates a key in .env and never runs it again. This costs a sha256
# of a 5 KB file and turns that into a line in the Sunday report.
SECRETS_NOTE=$(secrets_bundle_drift_note)

# The checksum goes to Telegram deliberately, and it is the only part of this
# message that is not just reassurance. Artifacts are encrypted to a PUBLIC
# key, so anyone able to write to a bucket can leave one there that decrypts
# and restores cleanly — the symmetric passphrase used to make that impossible.
# A checksum that has left the box, into a channel the bucket's credentials
# cannot reach, is what makes such a swap visible: compare before restoring.
SUMMARY="✅ Backup OK on $(hostname)
${ENCRYPTED_NAME} — $(human_bytes "${ENCRYPTED_SIZE}")
sha256 ${ENCRYPTED_SHA}
tiers: ${TIERS[*]} → ${BACKUP_DESTINATIONS[*]}
deep restore check: $([ "${DEEP_CHECK}" -eq 1 ] && echo passed || echo "not due")
${SECRETS_NOTE}"

log "=== Backup run ${STAMP} MSK finished successfully ==="

# Success is announced only on the nights the restore rehearsal ran. A daily
# "it worked" message is noise that trains you to ignore the failure message.
if [ "${DEEP_CHECK}" -eq 1 ]; then
    alert "${SUMMARY}"
fi

exit 0
