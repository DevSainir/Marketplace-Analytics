#!/usr/bin/env bash
# Backing up the secrets themselves: backend/.env, encrypted to an offline key
# and pushed to both buckets.
#
#   backend/scripts/backup/backup_secrets.sh [--env-file PATH] [--no-upload]
#
# Run this BY HAND, after any change to .env — a rotated key, a new storage,
# a changed database password. It is not on cron on purpose (see lib/secrets.sh
# for why), and the nightly job reports when .env has drifted away from the
# last bundle so that "by hand" does not become "never".
#
# The bundle is encrypted to recipients/secrets.txt, which names ONE key whose
# private half lives in a password manager and has never been on a server.
# This machine therefore cannot read back what it just wrote, and that is the
# feature: the bundle holds the Fernet key that unlocks every WB token in the
# nightly archives, so anything able to decrypt both on one box would undo the
# entire arrangement.
#
# Objects land under secrets/ and are NOT expired by a lifecycle policy. Every
# bundle is kept: recovering a database archive from March needs the Fernet key
# as it was in March, not the current one.

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
# shellcheck source=lib/secrets.sh
. "${SCRIPT_DIR}/lib/secrets.sh"

ENV_FILE="${BACKUP_ENV_FILE:-${BACKEND_DIR}/.env}"
PLAIN_BUNDLE=""
SECRETS_STAGE=""

while [ $# -gt 0 ]; do
    case $1 in
    --env-file)
        ENV_FILE=$2
        shift 2
        ;;
    --no-upload)
        BACKUP_SKIP_UPLOAD=1
        shift
        ;;
    -h | --help)
        sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    *)
        echo "Unknown argument: $1" >&2
        exit 2
        ;;
    esac
done

cleanup() {
    # The plaintext tar is every secret this project has, in one file. It must
    # not survive the run on any path out of it, successful or not.
    [ -n "${PLAIN_BUNDLE}" ] && rm -f "${PLAIN_BUNDLE}"
    [ -n "${SECRETS_STAGE}" ] && rm -rf "${SECRETS_STAGE}"
    return 0
}
trap cleanup EXIT

umask 077

load_env_file "${ENV_FILE}"
apply_backup_defaults

mkdir -p "${BACKUP_ARTIFACT_DIR}" "${BACKUP_STATE_DIR}" "${BACKUP_LOG_DIR}"
chmod 700 "${BACKUP_WORK_DIR}" "${BACKUP_ARTIFACT_DIR}" "${BACKUP_STATE_DIR}"
log_init "${BACKUP_LOG_DIR}/secrets-$(TZ="${BACKUP_TZ}" date +%Y%m%d).log"

require_secrets_config

STAMP=$(TZ="${BACKUP_TZ}" date +%Y%m%dT%H%M%S)
BUNDLE_NAME="secrets-${STAMP}msk.tar.gz.age"
PLAIN_BUNDLE="${BACKUP_ARTIFACT_DIR}/secrets-${STAMP}msk.tar.gz"
ENCRYPTED_BUNDLE="${BACKUP_ARTIFACT_DIR}/${BUNDLE_NAME}"

log "=== Secrets bundle ${STAMP} MSK ==="

create_secrets_bundle "${PLAIN_BUNDLE}" "${ENCRYPTED_BUNDLE}"

rm -f "${PLAIN_BUNDLE}"
PLAIN_BUNDLE=""

BUNDLE_SIZE=$(file_size "${ENCRYPTED_BUNDLE}")
BUNDLE_SHA=$(sha256_of "${ENCRYPTED_BUNDLE}")
log "Artifact ${BUNDLE_NAME}: $(human_bytes "${BUNDLE_SIZE}"), sha256 ${BUNDLE_SHA}."

if [ "${BACKUP_SKIP_UPLOAD:-0}" = "1" ]; then
    warn "--no-upload: nothing was pushed to ${BACKUP_DESTINATIONS[*]}."
else
    upload_all "${BUNDLE_NAME}" "${BUNDLE_SHA}" "${BUNDLE_SIZE}" secrets

    # Only after both buckets have the object and read it back. Recording the
    # fingerprint earlier would silence the staleness warning on a run that
    # never actually landed a bundle anywhere.
    secrets_env_fingerprint >"$(secrets_state_file)"
    chmod 600 "$(secrets_state_file)"
fi

# The encrypted bundle is not kept on the box. Unlike a database archive there
# is no same-week restore it would speed up, and the one machine that must
# never hold a copy of every secret is the one they are the secrets of.
rm -f "${ENCRYPTED_BUNDLE}"

log "=== Secrets bundle ${STAMP} MSK finished ==="

alert "🔐 Secrets bundle taken on $(hostname)
${BUNDLE_NAME} — $(human_bytes "${BUNDLE_SIZE}")
→ secrets/ on ${BACKUP_DESTINATIONS[*]}
Readable only with the offline key from the password manager."

exit 0
