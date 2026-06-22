#!/usr/bin/env bash
# correction-pair.sh — shared helpers for the correction-PAIRING pipeline.
#
# Captures the "AI did X → it got rejected" pair across three hooks so a rule is
# grounded in the real rejected change, not just the user's words:
#
#   edit-shadow-detector (PostToolUse, async) records files Claude writes
#   revert-detector       (PreToolUse,  async) cross-refs the shadow on git
#                                              revert/reset → records reverted_files
#   correction-detector   (UserPromptSubmit, sync) surfaces those files when the
#                                              user types an EXPLICIT correction
#
# The gate is enforced by the wiring: the two silent-signal hooks are async (their
# output is never fed back to the model), so a bare revert stays DATA ONLY. The
# pair is only injected into context when the user actually says something wrong —
# that path runs through the sync correction-detector.
#
# Session key: prefer the canonical session_id from the hook stdin JSON; fall back
# to $PPID only when absent (older Claude Code). session_id keeps the three hooks
# correlated across event types — $PPID can differ per hook invocation.

CP_SHADOW_DIR="${CP_SHADOW_DIR:-/tmp/claude-edit-shadows}"

# cp_session_key <input_json> — echo a stable, filesystem-safe per-session key.
cp_session_key() {
  local input="$1" sid=""
  if command -v jq >/dev/null 2>&1; then
    sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)
  fi
  if [[ -n "$sid" ]]; then
    printf '%s' "${sid//[^A-Za-z0-9_-]/_}"   # session ids are uuids; sanitize anyway
  else
    printf 'pid-%s' "$PPID"
  fi
}

# cp_shadow_file <session_key> — echo the shadow log path for a session.
cp_shadow_file() {
  printf '%s/session-%s.jsonl' "$CP_SHADOW_DIR" "$1"
}

# cp_recent_files <session_key> [limit] — echo recent DISTINCT files Claude touched
# this session, most-recent last, newline-separated (default limit 10).
cp_recent_files() {
  local key="$1" limit="${2:-10}" f
  f=$(cp_shadow_file "$key")
  [[ -f "$f" ]] || return 0
  command -v jq >/dev/null 2>&1 || return 0
  # last 80 records → file paths → keep last occurrence of each (preserve order) → tail
  tail -n 80 "$f" 2>/dev/null \
    | jq -r '.file // empty' 2>/dev/null \
    | awk 'NF { seen[$0]=NR; line[NR]=$0 } END { for (i=1;i<=NR;i++) if (seen[line[i]]==i) print line[i] }' \
    | tail -n "$limit"
}
