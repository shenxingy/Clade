#!/usr/bin/env bash
# notify-telegram.sh — Send Telegram notification when Claude needs attention
# exists-for: no incident recorded (added 2026-02-18 in 5e9103b); need: a phone alert when a session waits on a permission prompt or sits idle · retire-when: no install sets TG_BOT_TOKEN and TG_CHAT_ID, or Claude Code's own notifications reach the phone
# Triggered by Notification on permission_prompt|idle_prompt
#
# Setup: Set TG_BOT_TOKEN and TG_CHAT_ID in environment or ~/.claude/settings.json env

INPUT=$(cat)
MESSAGE=$(echo "$INPUT" | jq -r '.message // "Claude Code needs attention"')
TITLE=$(echo "$INPUT" | jq -r '.title // "Notification"')
TYPE=$(echo "$INPUT" | jq -r '.notification_type // "unknown"')

# Skip if Telegram not configured
if [[ -z "${TG_BOT_TOKEN:-}" || -z "${TG_CHAT_ID:-}" ]]; then
  exit 0
fi

# Format message based on type
case "$TYPE" in
  permission_prompt)
    ICON="🔐"
    ;;
  idle_prompt)
    ICON="💤"
    ;;
  *)
    ICON="🤖"
    ;;
esac

TEXT="${ICON} <b>Claude Code: ${TITLE}</b>
${MESSAGE}"

curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TG_CHAT_ID}" \
  -d "text=${TEXT}" \
  -d "parse_mode=HTML" > /dev/null 2>&1

exit 0
