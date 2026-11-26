#!/usr/bin/env bash
# session-end-cleanup.sh — Delete the ending session's correction-pairing shadow
# and, under Kimi, its first-prompt context sentinels.
# exists-for: correction-pairing shadows were removed only by an 8-hour sweep, leaving one stale file per short session (added 2026-08-10 in b81ec79); Kimi --once-per-session sentinels were never removed (12 on the author's main host, 2026-11-25) · retire-when: edit-shadow-detector.sh retires and decision-to-kimi.sh no longer claims sentinels; this deletes only what those two write
# Triggered by SessionEnd (all reasons: clear, logout, prompt_input_exit, other).
#
# edit-shadow-detector.sh writes <runtime>/claude-edit-shadows/session-<id>.jsonl
# and revert-detector/correction-detector read it (see lib/correction-pair.sh;
# <runtime> comes from lib/runtime-dir.sh and is private to this user).
# Nothing ever deleted them except the detector's own 8-hour sweep, so a machine
# that runs many short sessions accumulated one stale file per session.
#
# Attribution is the whole safety story: this deletes ONLY what is keyed by the
# session_id the host just ended — its shadow file and, under Kimi, its empty
# <id>.*.once sentinel dirs. Parallel live sessions own different session_ids,
# so their shadows and sentinels are never touched. No session_id (older Claude
# Code) means nothing is attributable — do nothing rather than guess from $PPID.
#
# Fail-open: any error is silently ignored; cleanup must never break session exit.

INPUT=$(cat)

command -v jq >/dev/null 2>&1 || exit 0
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
[[ -z "$SESSION_ID" ]] && exit 0

LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/correction-pair.sh" 2>/dev/null || true

# Kimi's --once-per-session sentinels (kimi-hooks/decision-to-kimi.sh): one
# empty directory per session and wrapped hook, <runtime>/kimi-session-context/
# <session_id>.<hook>.once. Kimi passes this SessionEnd the same session_id its
# first UserPromptSubmit claimed them under. The adapter only claims for an id
# of [A-Za-z0-9_-]+, so the raw id must pass the same test here — never the
# sanitizer below, which folds "a.b" onto "a_b", another session's key. With no
# dot in the id, "<id>.*.once" matches this session's names and no other id's.
# clade_runtime_dir fails closed on a squatted root; rmdir removes only an empty
# directory, never a file, a link or a directory with contents. It runs before
# the shadow checks below, which exit early when this session has no shadow.
if [[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]+$ ]] && ONCE_ROOT=$(clade_runtime_dir 2>/dev/null); then
  for SENTINEL in "$ONCE_ROOT/kimi-session-context/$SESSION_ID".*.once; do
    rmdir "$SENTINEL" 2>/dev/null
  done
fi

# Same derived root and same CP_SHADOW_DIR override the writers use
# (lib/correction-pair.sh → lib/runtime-dir.sh: a per-user scratch dir, not a
# fixed /tmp path). Empty means no root was resolvable — nothing of ours to
# clean, so do nothing rather than guess at a path.
SHADOW_DIR="${CP_SHADOW_DIR:-}"
[[ -z "$SHADOW_DIR" ]] && exit 0
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
