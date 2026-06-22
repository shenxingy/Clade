#!/usr/bin/env bash
# edit-shadow-detector.sh — Track files Claude edits, for correction PAIRING.
# Triggered by PostToolUse on Edit|Write (async — data only, output unused).
#
# Records each file Claude writes to a session-scoped shadow log. revert-detector
# and correction-detector read this log to recover the "AI did X → it got
# rejected" pair (which files a git revert threw away / which files the user is
# correcting). See lib/correction-pair.sh for the shared helpers and the gate.
#
# Fail-open: errors are silently ignored.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[[ -z "$FILE_PATH" ]] && exit 0

LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/correction-pair.sh" 2>/dev/null || true

SHADOW_DIR="${CP_SHADOW_DIR:-/tmp/claude-edit-shadows}"
mkdir -p "$SHADOW_DIR" 2>/dev/null

# Session-scoped key: canonical session_id (correlates across hook types), with a
# $PPID fallback for older Claude Code that doesn't pass session_id.
if declare -f cp_session_key >/dev/null 2>&1; then
  SHADOW_FILE=$(cp_shadow_file "$(cp_session_key "$INPUT")")
else
  SHADOW_FILE="$SHADOW_DIR/session-pid-$PPID.jsonl"
fi

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq -nc \
  --arg ts "$TIMESTAMP" \
  --arg file "$FILE_PATH" \
  '{timestamp: $ts, file: $file}' >> "$SHADOW_FILE" 2>/dev/null

# Clean up shadow files older than 8 hours
find "$SHADOW_DIR" -name "session-*.jsonl" -mmin +480 -delete 2>/dev/null

exit 0
