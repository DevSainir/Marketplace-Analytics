#!/usr/bin/env bash
# Logging and out-of-band alerting for the database backup job.
#
# The job runs from cron, so stdout is nobody's terminal: every line is also
# appended to a dated log file under the work directory. `die` is the only
# intended exit path for a failure, and it alerts BEFORE it exits — a backup
# that fails quietly is worse than no backup at all, because it is trusted.
#
# Alerting is optional and opt-in: with BACKUP_ALERT_TELEGRAM_* unset the
# functions are silent no-ops, so the script works out of the box.

BACKUP_LOG_FILE="${BACKUP_LOG_FILE:-}"

log_init() {
    BACKUP_LOG_FILE=$1
    mkdir -p "$(dirname "${BACKUP_LOG_FILE}")"
    touch "${BACKUP_LOG_FILE}"
    chmod 600 "${BACKUP_LOG_FILE}"
}

_log_line() {
    local level=$1
    shift
    local line
    line="$(TZ="${BACKUP_TZ:-Europe/Moscow}" date '+%Y-%m-%d %H:%M:%S %Z') [${level}] $*"
    printf '%s\n' "${line}"
    if [ -n "${BACKUP_LOG_FILE}" ]; then
        printf '%s\n' "${line}" >>"${BACKUP_LOG_FILE}"
    fi
    return 0
}

log() { _log_line INFO "$@"; }
warn() { _log_line WARN "$@"; }

# Fatal error: record it, push it to a human, stop. Never returns.
die() {
    _log_line ERROR "$@"
    alert "❌ Backup FAILED on $(hostname)
$*
Log: ${BACKUP_LOG_FILE:-<none>}"
    exit 1
}

# Best-effort notification. Never fails the run on its own — a backup that
# succeeded but could not be announced is still a backup.
alert() {
    local text=$1
    [ -n "${BACKUP_ALERT_TELEGRAM_BOT_TOKEN:-}" ] || return 0
    [ -n "${BACKUP_ALERT_TELEGRAM_CHAT_ID:-}" ] || return 0
    curl -sS -m 20 -o /dev/null \
        -X POST "https://api.telegram.org/bot${BACKUP_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${BACKUP_ALERT_TELEGRAM_CHAT_ID}" \
        --data-urlencode text="${text}" ||
        warn "Telegram alert could not be delivered."
    return 0
}

# Human-readable byte count, for log lines that a person reads at 09:00 after
# a 03:00 run.
human_bytes() {
    local bytes=$1
    awk -v b="${bytes}" 'BEGIN {
        split("B KiB MiB GiB TiB", u, " ")
        i = 1
        while (b >= 1024 && i < 5) { b /= 1024; i++ }
        printf (i == 1 ? "%d %s\n" : "%.1f %s\n"), b, u[i]
    }'
}
