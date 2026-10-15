#!/usr/bin/env bash
# Render alertmanager.yml from its template, filling in the Telegram credentials.
#
# Alertmanager has no environment-variable substitution and no `chat_id_file`,
# so the choice is between a config file that carries a live bot token and a
# config file that is generated. This generates it — the template is in git, the
# output is not.
#
# Run by `make obs-up`. Safe to run repeatedly; it overwrites its own output.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
template="$here/docker/observability/alertmanager.yml.template"
output="$here/docker/observability/alertmanager.yml"
env_file="$here/.env"

[[ -f "$env_file" ]] || { echo "render-alertmanager: $env_file not found." >&2; exit 1; }

read_var() {
  # Last assignment wins, matching how the file is read elsewhere. `cut` rather
  # than sourcing the file: sourcing it would execute whatever is in there, and
  # this script exists to handle secrets carefully.
  grep -E "^${1}=" "$env_file" | tail -n1 | cut -d= -f2- | tr -d "'\"" || true
}

token="$(read_var ALERT_TELEGRAM_BOT_TOKEN)"
chat="$(read_var ALERT_TELEGRAM_CHAT_ID)"

# A token and a chat id are a PAIR, and mixing halves from different pairs is
# the one failure this script must not produce. A Telegram chat id is per-BOT
# in effect: a bot can only message a chat that has started it, so the backup
# job's chat is unreachable to a freshly created alerting bot. Pairing a new
# token with the old chat id yields a config that loads cleanly, fires
# correctly, and delivers nothing — the worst outcome available here, because
# it looks exactly like a quiet system.
#
# So each pair falls back as a WHOLE or not at all: a dedicated token demands a
# dedicated chat id, and only when neither is set does the backup job's pair —
# which has alerted this team since it was written — get used entire.
if [[ -n "$token" || -n "$chat" ]]; then
  if [[ -z "$token" || -z "$chat" ]]; then
    echo "render-alertmanager: ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID" >&2
    echo "  must be set together. One without the other would pair a bot with a chat" >&2
    echo "  it cannot message, and Telegram reports that as a delivery failure long" >&2
    echo "  after the alert was supposed to arrive." >&2
    exit 1
  fi
else
  token="$(read_var BACKUP_ALERT_TELEGRAM_BOT_TOKEN)"
  chat="$(read_var BACKUP_ALERT_TELEGRAM_CHAT_ID)"
fi

if [[ -z "$token" || -z "$chat" ]]; then
  echo "render-alertmanager: no Telegram credentials in $env_file." >&2
  echo "  Set ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID (or the" >&2
  echo "  BACKUP_ALERT_TELEGRAM_* pair the backup job already uses)." >&2
  exit 1
fi

# `awk` with the values passed as variables, not `sed`: a bot token contains
# `:` and a chat id can be negative, and both would be interpreted as sed
# syntax or as a delimiter. Substituted with index/substr rather than gsub,
# because in a gsub replacement `&` means "the matched text", and how to escape
# it differs between mawk, gawk and BSD awk. The values are never echoed.
#
# There is no heartbeat URL to fill in any more. `Watchdog` used to be pushed
# to an external monitor from here (ALERT_HEARTBEAT_URL); it is now pulled —
# UptimeRobot polls the API's /healthz/alerts, which asks Alertmanager — so
# nothing in this file depends on an account outside the box.
awk -v tok="$token" -v chat="$chat" '
  function put(line, key, value,    at) {
    while ((at = index(line, key)) > 0) {
      line = substr(line, 1, at - 1) value substr(line, at + length(key))
    }
    return line
  }
  { print put(put($0, "__TELEGRAM_BOT_TOKEN__", tok), "__TELEGRAM_CHAT_ID__", chat) }
' "$template" > "$output"

# The container mounts this read-only and runs as nobody (65534) — the
# alertmanager image's own default user. A root-owned 0600 file is therefore
# unreadable to it, and Alertmanager restart-loops with "permission denied";
# that is exactly how this first went out.
#
# Give it away as narrowly as the host allows. Handing the file to 65534 and
# keeping 0600 is the tightest arrangement that works: readable by the one
# process that needs it, and by root, and by nobody else. `chown` needs
# privileges, which the deploy has and a developer's laptop does not — hence
# the fallback, which widens to 0644 only when there was no other option and
# says so rather than failing.
ALERTMANAGER_UID=65534
chmod 600 "$output"
if chown "$ALERTMANAGER_UID:$ALERTMANAGER_UID" "$output" 2>/dev/null; then
  perms="0600, owned by uid $ALERTMANAGER_UID"
else
  chmod 644 "$output"
  perms="0644 (could not chown; unprivileged host)"
fi

echo "render-alertmanager: wrote ${output#"$here"/} — $perms (bot token ${#token} chars, chat ${chat})"
