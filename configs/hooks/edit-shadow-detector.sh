#!/usr/bin/env bash
# edit-shadow-detector.sh — Track files Claude edits for implicit correction detection
# Triggered by PostToolUse on Edit|Write
#
# Records each Claude edit to a session-local temp file.
# The correction-detector.sh reads this to detect when a user edits
# a file Claude recently touched (implicit correction signal).
#
# Fail-open: errors are silently ignored.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Write to session-scoped shadow file (PID of parent claude process)
SHADOW_DIR="/tmp/claude-edit-shadows"
mkdir -p "$SHADOW_DIR" 2>/dev/null
SHADOW_FILE="$SHADOW_DIR/session-$PPID.jsonl"

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

jq -n \
  --arg ts "$TIMESTAMP" \
  --arg file "$FILE_PATH" \
  '{timestamp: $ts, file: $file}' >> "$SHADOW_FILE" 2>/dev/null

# Clean up shadow files older than 8 hours
find "$SHADOW_DIR" -name "session-*.jsonl" -mmin +480 -delete 2>/dev/null

exit 0
