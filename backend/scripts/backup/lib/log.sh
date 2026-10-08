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
#
# --fail-with-body is not decoration: without it curl exits 0 on an HTTP 400,
# so a wrong chat id or a revoked token would look exactly like a delivered
# message. An alerting channel nobody has ever seen fail is the one that turns
# out to be broken on the night it matters.
#
# disable_notification is a project-wide invariant: every message this project
# sends arrives silently, so a 03:00 backup never wakes anyone. The alert is
# still there at 09:00, which is when it gets acted on anyway.
#
# A network failure is retried, an HTTP one is not. The route from this host to
# api.telegram.org drops a share of connects outright (IPv4 to 149.154.166.110
# times out, IPv6 times out about one try in five — measured 2026-10-08), and
# on 2026-10-07 a single timeout swallowed the alert for a failed backup while
# the log called it "rejected". curl's exit 22 is the server answering 4xx/5xx,
# which a second try will not change; every other exit is the path.
alert() {
    local text=$1 response rc attempt
    local attempts=${BACKUP_ALERT_ATTEMPTS:-3}
    [ -n "${BACKUP_ALERT_TELEGRAM_BOT_TOKEN:-}" ] || return 0
    [ -n "${BACKUP_ALERT_TELEGRAM_CHAT_ID:-}" ] || return 0

    for ((attempt = 1; attempt <= attempts; attempt++)); do
        rc=0
        response=$(_telegram_send "${text}") || rc=$?
        [ "${rc}" -eq 0 ] && break
        # Never echo the response verbatim — the URL it came from carries the
        # bot token, and this line lands in a log file.
        if [ "${rc}" -eq 22 ]; then
            warn "Telegram alert was rejected (HTTP error); check BACKUP_ALERT_TELEGRAM_*."
            return 0
        fi
        if [ "${attempt}" -lt "${attempts}" ]; then
            sleep "${BACKUP_ALERT_RETRY_DELAY_SECONDS:-10}"
        fi
    done
    if [ "${rc}" -ne 0 ]; then
        warn "Telegram unreachable after ${attempts} attempts (curl exit ${rc}); the alert was not delivered."
        return 0
    fi
    case ${response} in
    *'"ok":true'*) return 0 ;;
    *) warn "Telegram accepted the request but did not confirm delivery." ;;
    esac
    return 0
}

# One POST to the Bot API; prints the body, returns curl's exit code. Separate
# from `alert` so the retry policy can be exercised without the network.
_telegram_send() {
    curl -sS -m 20 --fail-with-body \
        -X POST "https://api.telegram.org/bot${BACKUP_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${BACKUP_ALERT_TELEGRAM_CHAT_ID}" \
        -d disable_notification=true \
        --data-urlencode text="$1" 2>&1
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
