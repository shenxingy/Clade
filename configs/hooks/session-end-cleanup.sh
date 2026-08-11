#!/usr/bin/env bash
# session-end-cleanup.sh — Delete the ending session's correction-pairing shadow.
# Triggered by SessionEnd (all reasons: clear, logout, prompt_input_exit, other).
#
# edit-shadow-detector.sh writes /tmp/claude-edit-shadows/session-<id>.jsonl and
# revert-detector/correction-detector read it (see lib/correction-pair.sh).
# Nothing ever deleted them except the detector's own 8-hour sweep, so a machine
# that runs many short sessions accumulated one stale file per session.
#
# Attribution is the whole safety story: this deletes ONLY the single file keyed
# by the session_id Claude Code just ended. Parallel live sessions own different
# session_ids, so their shadows are never touched. No session_id (older Claude
# Code) means no attributable file — do nothing rather than guess from $PPID.
#
# Fail-open: any error is silently ignored; cleanup must never break session exit.

INPUT=$(cat)

command -v jq >/dev/null 2>&1 || exit 0
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
[[ -z "$SESSION_ID" ]] && exit 0

LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/correction-pair.sh" 2>/dev/null || true

# Same default and same CP_SHADOW_DIR override the writers use.
SHADOW_DIR="${CP_SHADOW_DIR:-/tmp/claude-edit-shadows}"
[[ -d "$SHADOW_DIR" ]] || exit 0

# Same sanitizer as cp_session_key, applied to the id we already proved present
# (cp_session_key itself falls back to pid-$PPID when session_id is absent —
# that fallback would target another session's file, so it must not be used here).
KEY="${SESSION_ID//[^A-Za-z0-9_-]/_}"
[[ -z "$KEY" ]] && exit 0

if declare -f cp_shadow_file >/dev/null 2>&1; then
  SHADOW_FILE=$(cp_shadow_file "$KEY")
else
  SHADOW_FILE="$SHADOW_DIR/session-$KEY.jsonl"
fi

# Rail: only ever unlink a session-*.jsonl directly inside the shadow dir.
case "$SHADOW_FILE" in
  "$SHADOW_DIR"/session-*.jsonl) ;;
  *) exit 0 ;;
esac
case "$SHADOW_FILE" in
  */../*) exit 0 ;;
esac

# rm on a symlink unlinks the link itself, never the target — safe either way.
rm -f "$SHADOW_FILE" 2>/dev/null

exit 0
