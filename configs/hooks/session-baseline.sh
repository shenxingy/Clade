#!/usr/bin/env bash
# session-baseline.sh — SessionStart hook
#
# Captures git dirty state at session start so stop-check.sh can compute
# session-scoped deltas — i.e., only block stops on changes THIS session
# produced, not pre-existing dirt from parallel CC sessions on the same repo.
#
# Baseline file: $PROJECT/.claude/sessions/<session_id>.baseline
# Format: sorted `git status --porcelain` output (excluding .claude/ paths,
# which stop-check already ignores).

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree &>/dev/null || exit 0

# Read session_id from hook input JSON (stdin)
HOOK_INPUT=""
if [ ! -t 0 ]; then
  HOOK_INPUT=$(cat 2>/dev/null || true)
fi
SESSION_ID=""
if command -v jq &>/dev/null && [ -n "$HOOK_INPUT" ]; then
  SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
fi
[ -z "$SESSION_ID" ] && exit 0

SESS_DIR="$PROJECT_DIR/.claude/sessions"
mkdir -p "$SESS_DIR" 2>/dev/null || exit 0

# Capture baseline: sorted porcelain output, excluding .claude/ paths
# Porcelain format: "XY path" — path starts at column 4
git status --porcelain 2>/dev/null \
  | awk 'substr($0,4) !~ /^\.claude\// { print }' \
  | LC_ALL=C sort \
  > "$SESS_DIR/$SESSION_ID.baseline" 2>/dev/null || true

# Cleanup: remove baselines and counters older than 7 days
find "$SESS_DIR" -maxdepth 1 -type f \( -name '*.baseline' -o -name '*.stop_attempts' \) -mtime +7 -delete 2>/dev/null || true

exit 0
