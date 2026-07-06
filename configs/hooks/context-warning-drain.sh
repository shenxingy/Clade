#!/usr/bin/env bash
# context-warning-drain.sh — PostToolUse hook (all tools)
#
# Round-4 dead-code fix (fennu2333 / Chorus): worker.py's poll_all() writes
#   $CLAUDE_PROJECT_DIR/.claude/context-warning-<task_id>.md
# once a running worker's estimated tokens cross ~80% of the context window —
# but nothing ever delivered that file INTO the worker's own session (confirmed
# via grep: zero readers existed since it was introduced). This hook is the
# missing delivery channel, mirroring mailbox-drain.sh's pattern exactly.
#
# Delivery semantics:
#   - Drained AT MOST ONCE: atomic mv-then-read claims the file before reading,
#     so a racing second drainer can never split or double-deliver the nudge.
#   - Consumed (deleted), not just injected — this is a one-shot "you're at
#     80%, /compact now" nudge, not a repeating steering message. worker.py's
#     `if not warn_file.exists()` guard means only one file is ever written per
#     worker anyway; consuming it here just closes the loop.
#   - Non-worker sessions: CLADE_WORKER_TASK_ID is unset (worker.py exports it
#     only into orchestrator worker env), so this hook is a no-op everywhere
#     else.
#
# Output: hookSpecificOutput.additionalContext with the warning content.
# Silent (no output, exit 0) when there is nothing to drain — failure paths
# included.

set -u

command -v jq &>/dev/null || exit 0

if [ ! -t 0 ]; then
  cat > /dev/null 2>&1 || true
fi

TASK_ID="${CLADE_WORKER_TASK_ID:-}"
[ -z "$TASK_ID" ] && exit 0

# Path-safety: the env var is orchestrator-set, but never interpolate
# uncontrolled text into a filesystem path (defense in depth).
case "$TASK_ID" in
  *[!A-Za-z0-9._-]*) exit 0 ;;
esac

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
WARN_FILE="$PROJECT_DIR/.claude/context-warning-$TASK_ID.md"

# Regular file only — refuse symlinks so a planted link can never pull
# arbitrary file content into the worker's context.
[ -L "$WARN_FILE" ] && exit 0
[ -f "$WARN_FILE" ] || exit 0

# Atomic claim: rename first, read after (same rationale as mailbox-drain.sh).
DRAIN="$WARN_FILE.draining.$$"
mv -- "$WARN_FILE" "$DRAIN" 2>/dev/null || exit 0

CONTENT=$(head -c 2000 "$DRAIN" 2>/dev/null || true)
rm -f -- "$DRAIN"

[ -z "$CONTENT" ] && exit 0

jq -n --arg ctx "[Context budget warning]
$CONTENT" \
  '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":$ctx}}'

exit 0
