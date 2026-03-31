#!/usr/bin/env bash
# pre-compact.sh — Saves lightweight task state before Claude Code compacts the context.
# Triggered by: PreCompact hook event
# Purpose: After compaction, the session can reload .claude/compact-state.md to remember
#          what was being worked on.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
CLAUDE_DIR="$PROJECT_DIR/.claude"
mkdir -p "$CLAUDE_DIR"

STATE_FILE="$CLAUDE_DIR/compact-state.md"

{
  echo "# Pre-compact State: $(date '+%Y-%m-%d %H:%M')"
  echo ""
  echo "## Current Task"
  if [ -f "$CLAUDE_DIR/current-task.md" ]; then
    cat "$CLAUDE_DIR/current-task.md"
  else
    echo "(no current-task.md found)"
  fi
  echo ""
  echo "## Recent Commits"
  git -C "$PROJECT_DIR" log --oneline -8 2>/dev/null || echo "(git unavailable)"
  echo ""
  echo "## Uncommitted Changes"
  git -C "$PROJECT_DIR" status -sb 2>/dev/null || echo "(git unavailable)"
  echo ""
  echo "## Open TODO Items"
  if [ -f "$PROJECT_DIR/TODO.md" ]; then
    grep '^\- \[ \]' "$PROJECT_DIR/TODO.md" 2>/dev/null | head -10 || echo "(none found)"
  else
    echo "(no TODO.md)"
  fi
} > "$STATE_FILE"

# Output as comment so Claude sees it was saved
echo "<!-- PreCompact hook: state saved to .claude/compact-state.md -->"
echo "<!-- After compaction, read .claude/compact-state.md to restore task context -->"
