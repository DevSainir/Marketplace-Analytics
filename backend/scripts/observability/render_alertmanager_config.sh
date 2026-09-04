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

# Fall back to the backup job's bot, which has alerted this team since it was
# written. Reusing it means alerting works with the credentials already on the
# box; setting the dedicated pair splits them later without touching anything
# else.
[[ -n "$token" ]] || token="$(read_var BACKUP_ALERT_TELEGRAM_BOT_TOKEN)"
[[ -n "$chat" ]] || chat="$(read_var BACKUP_ALERT_TELEGRAM_CHAT_ID)"

if [[ -z "$token" || -z "$chat" ]]; then
  echo "render-alertmanager: no Telegram credentials in $env_file." >&2
  echo "  Set ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID (or the" >&2
  echo "  BACKUP_ALERT_TELEGRAM_* pair the backup job already uses)." >&2
  exit 1
fi

# `awk` with the value passed as a variable, not `sed`: a bot token contains
# `:` and a chat id can be negative, and both would be interpreted as sed
# syntax or as a delimiter. The value is never echoed.
awk -v tok="$token" -v chat="$chat" '
  { gsub(/__TELEGRAM_BOT_TOKEN__/, tok); gsub(/__TELEGRAM_CHAT_ID__/, chat); print }
' "$template" > "$output"

chmod 600 "$output"
echo "render-alertmanager: wrote ${output#"$here"/} (bot token ${#token} chars, chat ${chat})"
