#!/usr/bin/env bash
# pre-compact.sh — Saves a repository snapshot before Claude Code compacts the context.
# exists-for: no incident recorded (added 2026-03-30 in 08cca1e); need: save the active task state before compaction so it can be reloaded · retire-when: an ablation over compacted sessions shows Claude Code's own summary keeps the task goal; post-compact-reinject.sh retires with it
# Triggered by: PreCompact hook event
# Purpose: After compaction, the session can reload .claude/compact-state.md to remember
#          where the repository stood.
#
# It records a TASK only when .claude/current-task.md exists, and in practice
# nothing writes that file: every post-compaction restore on the author's
# machine (25 of 25, 2026-09-18 → 10-26) said so, and 19 of them carried open
# TODO items. Those items are backlog. The snapshot says both things in its own
# words, because post-compact-reinject.sh and session-context.sh frame it by
# whether a task was recorded (they look for "(none recorded", or the older
# "(no current-task.md found)" a not-yet-updated install still writes).

set -euo pipefail

INPUT=$(cat 2>/dev/null || true)

# ─── A subagent compacting is not the project's state ────────────────
# Claude Code fires PreCompact for a subagent's compaction too. Writing the
# snapshot then refreshes compact-state.md's mtime, which keeps
# session-context.sh's two-hour window open for new sessions on a snapshot no
# main-thread compaction wrote. A subagent is recognised the way
# post-compact-reinject.sh recognises one: agent_id (Claude Code 2.1.323+), or
# a transcript under subagents/. Without jq nothing is known, and it writes as
# before.
if command -v jq >/dev/null 2>&1 && [ -n "$INPUT" ]; then
  _agent=$(printf '%s' "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null || true)
  _transcript=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)
  case "$_transcript" in
    */subagents/agent-*.jsonl|*/subagents/*/agent-*.jsonl) _agent=${_agent:-subagent} ;;
  esac
  [ -z "$_agent" ] || exit 0
fi

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
    echo "(none recorded — this snapshot carries no task; the conversation says what you are doing)"
  fi
  echo ""
  echo "## Recent Commits"
  git -C "$PROJECT_DIR" log --oneline -8 2>/dev/null || echo "(git unavailable)"
  echo ""
  echo "## Uncommitted Changes"
  git -C "$PROJECT_DIR" status -sb 2>/dev/null || echo "(git unavailable)"
  echo ""
  echo "## Open TODO Items (backlog, not the current task)"
  if [ -f "$PROJECT_DIR/TODO.md" ]; then
    grep '^\- \[ \]' "$PROJECT_DIR/TODO.md" 2>/dev/null | head -10 || echo "(none found)"
  else
    echo "(no TODO.md)"
  fi
} > "$STATE_FILE"

# Output as comment so Claude sees it was saved
echo "<!-- PreCompact hook: state saved to .claude/compact-state.md -->"
echo "<!-- After compaction it is re-injected as orientation; it is not an instruction -->"
