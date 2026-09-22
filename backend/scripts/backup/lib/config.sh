#!/usr/bin/env bash
# Configuration for the database backup job: read backend/.env, apply the
# defaults, refuse to start on anything missing.
#
# The .env file is PARSED, not sourced. Sourcing would expand `$` inside a
# password and execute anything else the file happens to contain — this file
# holds the Postgres password, the Fernet key and both sets of S3 credentials,
# and it is the last place that should double as a shell script. The parser
# below mirrors what docker compose accepts: KEY=VALUE, optional `export`,
# optional quotes, and an inline `#` comment only when preceded by whitespace.
#
# Precedence is the usual dotenv one — a variable already present and non-empty
# in the environment wins, so an operator can override a single knob for one
# run without editing the file.

# Where this library lives, so the public recipient lists can be found next to
# the scripts rather than named in .env. They are not secret, and keeping them
# in git is exactly what lets a test pin them.
BACKUP_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

load_env_file() {
    local file=$1 line key value
    [ -r "${file}" ] || die "Environment file not readable: ${file}"

    while IFS= read -r line || [ -n "${line}" ]; do
        line=${line%$'\r'}
        case ${line} in '' | '#'*) continue ;; esac
        line=${line#export }
        case ${line} in *=*) ;; *) continue ;; esac

        key=${line%%=*}
        value=${line#*=}
        key=${key//[[:space:]]/}
        [[ ${key} =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

        value=${value#"${value%%[![:space:]]*}"} # ltrim
        case ${value} in
        '"'*)
            value=${value#\"}
            value=${value%%\"*}
            ;;
        "'"*)
            value=${value#\'}
            value=${value%%\'*}
            ;;
        *)
            value=${value%%[[:space:]]#*}                 # inline comment
            value=${value%"${value##*[![:space:]]}"}      # rtrim
            ;;
        esac

        if [ -z "${!key:-}" ]; then
            printf -v "${key}" '%s' "${value}"
            export "${key?}"
        fi
    done <"${file}"
}

# Every knob the job needs, with the defaults that make it work unchanged on
# the VPS. Anything genuinely deployment-specific has no default and is
# checked by require_config below.
apply_backup_defaults() {
    : "${BACKUP_TZ:=Europe/Moscow}"
    : "${BACKUP_WORK_DIR:=/var/backups/marketplace}"

    # Encryption. Artifacts are age-encrypted to the public keys listed in
    # recipients/, and BACKUP_ENCRYPTION_IDENTITY is the *online* private half
    # — the one that lets the Sunday rehearsal decrypt unattended. The offline
    # half is in a password manager and is not on this machine by design.
    : "${BACKUP_RECIPIENTS_DIR:=${BACKUP_LIB_DIR}/../recipients}"
    : "${BACKUP_DB_RECIPIENTS:=${BACKUP_RECIPIENTS_DIR}/database.txt}"
    : "${BACKUP_SECRETS_RECIPIENTS:=${BACKUP_RECIPIENTS_DIR}/secrets.txt}"

    # Where the dump comes from: a throwaway pg_dump container attached to the
    # stack's network, rather than `docker exec` into the running Postgres.
    # pg_dump's memory would otherwise count against the postgres container's
    # 384 MB cgroup ceiling and could get the live database OOM-killed at 03:00.
    : "${BACKUP_DOCKER_NETWORK:=marketplace-service_default}"
    : "${BACKUP_PG_HOST:=postgres}"
    : "${BACKUP_PG_IMAGE:=postgres:16-alpine}"
    : "${BACKUP_AWSCLI_IMAGE:=amazon/aws-cli:2.36.19}"

    # Validity gates. MIN_BYTES is an absolute floor; SHRINK_PCT catches the
    # more realistic failure — a dump that succeeded but came out truncated,
    # which an absolute floor would happily wave through.
    : "${BACKUP_MIN_BYTES:=10485760}" # 10 MiB
    : "${BACKUP_SHRINK_PCT:=50}"      # fail under 50% of the previous run

    # ISO day of week (1=Mon … 7=Sun) for the weekly tier and for the deep
    # restore rehearsal. They are deliberately the same day.
    : "${BACKUP_WEEKLY_DOW:=7}"
    : "${BACKUP_DEEP_CHECK_DOW:=7}"
    : "${BACKUP_FORCE_DEEP_CHECK:=0}"

    # Restore rehearsal ceilings: a scratch Postgres, capped so it cannot
    # squeeze the live stack on a 3.8 GB box, and a wall clock so a hung
    # restore does not sit on the lock until the next night's run.
    : "${BACKUP_RESTORE_MEM:=768m}"
    : "${BACKUP_RESTORE_CPUS:=1.0}"
    : "${BACKUP_RESTORE_TIMEOUT_SECONDS:=2400}"

    : "${BACKUP_LOCAL_KEEP:=3}"   # encrypted dumps kept on disk
    : "${BACKUP_LOG_KEEP_DAYS:=60}"
    : "${BACKUP_UPLOAD_RETRIES:=3}"

    BACKUP_ARTIFACT_DIR="${BACKUP_WORK_DIR}/artifacts"
    BACKUP_STATE_DIR="${BACKUP_WORK_DIR}/state"
    BACKUP_LOG_DIR="${BACKUP_WORK_DIR}/logs"
    export BACKUP_ARTIFACT_DIR BACKUP_STATE_DIR BACKUP_LOG_DIR
}

# The two object storages, in the order they are written. Each name expands to
# ${NAME}_ENDPOINT / _BUCKET / _KEY / _SECRET / _REGION via dest_var below.
# Kept as data so adding a third storage is one line here and nothing else.
BACKUP_DESTINATIONS=(hoster cloudfare)

dest_var() {
    local dest=$1 field=$2
    case "${dest}:${field}" in
    hoster:endpoint) printf '%s' "${S3_HOSTER_URL:-}" ;;
    hoster:bucket) printf '%s' "${S3_HOSTER_BUCKET:-}" ;;
    hoster:key) printf '%s' "${S3_HOSTER_ACCESS_KEY:-}" ;;
    hoster:secret) printf '%s' "${S3_HOSTER_SECRET_ACCESS_KEY:-}" ;;
    hoster:region) printf '%s' "${HOSTER_DEFAULT_REGION_NAME:-ru-1}" ;;
    cloudfare:endpoint) printf '%s' "${S3_CLOUDFARE_URL:-}" ;;
    cloudfare:bucket) printf '%s' "${S3_CLOUDFARE_BUCKET:-}" ;;
    cloudfare:key) printf '%s' "${S3_CLOUDFARE_ACCESS_KEY:-}" ;;
    cloudfare:secret) printf '%s' "${S3_CLOUDFARE_SECRET_ACCESS_KEY:-}" ;;
    cloudfare:region) printf '%s' "${CLOUDFARE_DEFAULT_REGION_NAME:-auto}" ;;
    *) return 1 ;;
    esac
}

# Fail before the dump rather than after it: a missing bucket name discovered
# at upload time has already cost ten minutes of pg_dump and left an
# unencrypted artifact on disk.
require_config() {
    local missing=() dest field

    for field in POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD BACKUP_ENCRYPTION_IDENTITY; do
        [ -n "${!field:-}" ] || missing+=("${field}")
    done

    for dest in "${BACKUP_DESTINATIONS[@]}"; do
        for field in endpoint bucket key secret; do
            [ -n "$(dest_var "${dest}" "${field}")" ] ||
                missing+=("${dest}/${field}")
        done
    done

    if [ ${#missing[@]} -gt 0 ]; then
        die "Missing configuration: ${missing[*]}. See backend/.env.example."
    fi

    command -v docker >/dev/null || die "docker is not on PATH."
    command -v age >/dev/null || die "age is not installed (apt-get install age)."

    # gpg is no longer used to WRITE anything. It stays required because the
    # buckets still hold symmetric .gpg artifacts from before 2026-09-21, and
    # restore.sh has to be able to open them for as long as they exist — the
    # monthly tier keeps them for a year.
    command -v gpg >/dev/null || die "gpg is not installed (still needed for pre-age archives)."

    [ -r "${BACKUP_DB_RECIPIENTS}" ] ||
        die "Recipient list not readable: ${BACKUP_DB_RECIPIENTS}"
    [ "$(recipient_count "${BACKUP_DB_RECIPIENTS}")" -ge 2 ] ||
        die "${BACKUP_DB_RECIPIENTS} names fewer than two recipients — the offline key is what survives losing this box."
    docker network inspect "${BACKUP_DOCKER_NETWORK}" >/dev/null 2>&1 ||
        die "Docker network ${BACKUP_DOCKER_NETWORK} does not exist — is the stack up?"
}

# The recipients age will actually use: every line that is not blank and not a
# comment. Used both to configure the encryption and, afterwards, to check that
# the artifact really carries one stanza per recipient.
recipient_count() {
    grep -cE '^[[:space:]]*age1' "$1" || true
}
