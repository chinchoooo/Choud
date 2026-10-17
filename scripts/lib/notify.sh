#!/usr/bin/env bash
# Failure alerts by webhook. Source this file, then call:
#
#     notify_event <key> <ok|fail> "<title>" "<message>"
#
# With ALERT_WEBHOOK_URL unset this does nothing, so scripts can call it unconditionally.
#
# To avoid being spammed by a timer that runs every few minutes it only speaks on *changes*:
#   - the first "fail" for a key sends one alert,
#   - further "fail"s stay quiet until ALERT_REMINDER_HOURS (default 24) have passed,
#   - the first "ok" after a failure sends one "recovered" message,
#   - "ok" while everything is fine sends nothing.
#
# The webhook can be ntfy (https://ntfy.sh/<topic>, the default format), Discord
# (https://discord.com/api/webhooks/...) or Slack (https://hooks.slack.com/...); the format is
# picked from the URL. A failure to deliver an alert never makes the calling script fail.
#
# Settings (environment / .env):
#   ALERT_WEBHOOK_URL       where to post; empty disables alerts
#   ALERT_REMINDER_HOURS    how often to repeat while still failing (default 24)
#   ALERT_STATE_DIR         where the last-known state is kept (default: $TMPDIR or /var/tmp)

_alert_json_escape() {
    # backslash, double quote, then newlines/tabs/CRs
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk 'BEGIN{ORS="\\n"} {print}' | sed -e 's/\\n$//' -e 's/\t/\\t/g' -e 's/\r//g'
}

_alert_send() {
    local title="$1" message="$2" url="${ALERT_WEBHOOK_URL:-}"
    [ -n "$url" ] || return 0
    case "$url" in
        *discord.com/api/webhooks*|*discordapp.com/api/webhooks*)
            curl -fsS --max-time 10 -H 'Content-Type: application/json' \
                -d "{\"content\":\"**$(_alert_json_escape "$title")**\\n$(_alert_json_escape "$message")\"}" \
                "$url" >/dev/null 2>&1 || echo "alert: could not reach the Discord webhook" >&2
            ;;
        *hooks.slack.com*)
            curl -fsS --max-time 10 -H 'Content-Type: application/json' \
                -d "{\"text\":\"*$(_alert_json_escape "$title")*\\n$(_alert_json_escape "$message")\"}" \
                "$url" >/dev/null 2>&1 || echo "alert: could not reach the Slack webhook" >&2
            ;;
        *)
            # ntfy-style: the message is the body, the title and priority are headers.
            curl -fsS --max-time 10 -H "Title: ${title}" -H 'Priority: high' -d "$message" \
                "$url" >/dev/null 2>&1 || echo "alert: could not reach the webhook" >&2
            ;;
    esac
    return 0
}

notify_event() {
    local key="$1" status="$2" title="$3" message="${4:-}"
    [ -n "${ALERT_WEBHOOK_URL:-}" ] || return 0

    local dir="${ALERT_STATE_DIR:-${TMPDIR:-/var/tmp}}/personal-cloud-alerts"
    mkdir -p "$dir" 2>/dev/null || return 0
    local file="${dir}/${key}.state" now previous="ok" last_sent=0
    now="$(date +%s)"
    if [ -f "$file" ]; then
        read -r previous last_sent <"$file" || true
        previous="${previous:-ok}"
        last_sent="${last_sent:-0}"
    fi
    local reminder=$(( ${ALERT_REMINDER_HOURS:-24} * 3600 ))

    if [ "$status" = "fail" ]; then
        if [ "$previous" != "fail" ] || [ $(( now - last_sent )) -ge "$reminder" ]; then
            _alert_send "$title" "$message"
            printf 'fail %s\n' "$now" >"$file"
        fi
    else
        if [ "$previous" = "fail" ]; then
            _alert_send "Recovered: ${title}" "${message:-Everything is back to normal.}"
        fi
        printf 'ok %s\n' "$now" >"$file"
    fi
    return 0
}
