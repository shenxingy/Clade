#!/usr/bin/env bash
# post-compact-reinject.sh — SessionStart hook (matcher: compact)
#
# Closes a "Defined ≠ called" wiring hole. The PreCompact hook already SAVES
# active task state to .claude/compact-state.md (pre-compact.sh), and
# session-context.sh can RELOAD it — but that reload only ran under
# matcher:"startup", which never fires on a compaction. Claude Code fires
# SessionStart with source "compact" for BOTH auto- and manual (/compact)
# compaction (docs: "Auto or manual compaction"); a startup-only matcher misses
# it, so after an in-session auto-compaction the pinned task goal was silently
# lost — exactly the long-run failure the orchestrator exists to prevent.
#
# This hook is the missing "after" half. On the compact source it re-injects
# ONLY the pinned invariants (the saved task goal/state). It is deliberately
# lean: it does NOT re-run the heavy startup session-context.sh (git fetch /
# memory-sync / commit-archeology), which would dump the full context blob on
# every compaction.
#
# It also clears the path-scoped rule sentinel (<session_id>.rules-injected) so
# rules that compaction dropped re-inject on the next matching Edit/Write via
# rule-injector.sh. Path-scoped rules matter most exactly when you next touch a
# matching path, so re-arming on the next edit is the correct semantics (and
# reuses the already-tested injector path instead of duplicating its parser).
#
# Output: hookSpecificOutput.additionalContext with the saved state. Silent
# (no output, exit 0) whenever there is nothing fresh to restore.

set -u

command -v jq >/dev/null 2>&1 || exit 0

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat 2>/dev/null || true)
fi

# Belt-and-braces: only act on the compaction source even if the matcher widens
# later. An empty source (e.g. a bare `echo '{}' | hook` in tests) still proceeds.
SOURCE=$(printf '%s' "$INPUT" | jq -r '.source // empty' 2>/dev/null || true)
if [ -n "$SOURCE" ] && [ "$SOURCE" != "compact" ]; then
  exit 0
fi

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
CLAUDE_DIR="$PROJECT_DIR/.claude"

# ─── Re-arm path-scoped rules dropped by compaction ──────────────────
# rule-injector.sh injects each rule file at most once/session via this sentinel.
# Compaction erases the injected rule text, so clear the sentinel: the next edit
# to a matching path re-injects the rule through the already-tested injector.
if [ -n "$SESSION_ID" ]; then
  rm -f "$CLAUDE_DIR/sessions/${SESSION_ID}.rules-injected" 2>/dev/null || true
fi

# ─── Re-inject the pinned task goal / working state ──────────────────
# compact-state.md is written by pre-compact.sh immediately before compaction.
# Guard on age (< 2h, mirrors session-context.sh) so a stale file from a much
# earlier run is not resurfaced.
COMPACT_STATE="$CLAUDE_DIR/compact-state.md"
[ -f "$COMPACT_STATE" ] || exit 0

CS_MTIME=$(stat -c %Y "$COMPACT_STATE" 2>/dev/null || stat -f %m "$COMPACT_STATE" 2>/dev/null || echo 0)
CS_AGE_HOURS=$(( ( $(date +%s) - CS_MTIME ) / 3600 ))
[ "$CS_AGE_HOURS" -lt 2 ] || exit 0

COMPACT_CONTENT=$(cat "$COMPACT_STATE" 2>/dev/null)
[ -n "$COMPACT_CONTENT" ] || exit 0

CTX="## Post-compaction restore (the conversation was just compacted)
Your task state below was saved immediately before compaction — resume from it
rather than re-deriving intent from the summary. Path-scoped rules re-inject when
you next edit a matching file.

${COMPACT_CONTENT}"

jq -n --arg ctx "$CTX" \
  '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'

exit 0
