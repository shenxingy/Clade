#!/bin/bash
# stop-check.sh — Verify this session left a clean slate before stopping.
#
# Session-scoped: only flags dirty files that appeared or changed status
# DURING this session. Files already dirty at session start (e.g., from a
# parallel CC session on the same repo) are ignored — not this session's
# responsibility. Requires session-baseline.sh to have captured a baseline
# at SessionStart.
#
# Circuit breaker: cooperates with Claude Code's `stop_hook_active` field
# AND tracks a local attempt counter — after N consecutive blocks in one
# session, falls back to exit 0 with a warning to avoid deadlocking the LLM.
#
# Companion: configs/hooks/session-baseline.sh captures the baseline.

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree &>/dev/null || exit 0

# ─── Parse hook input ────────────────────────────────────────────────
HOOK_INPUT=""
if [ ! -t 0 ]; then
  HOOK_INPUT=$(cat 2>/dev/null || true)
fi
SESSION_ID=""
STOP_ACTIVE="false"
if command -v jq &>/dev/null && [ -n "$HOOK_INPUT" ]; then
  SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
  STOP_ACTIVE=$(echo "$HOOK_INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo false)
fi

SESS_DIR="$PROJECT_DIR/.claude/sessions"
BASELINE_FILE=""
ATTEMPTS_FILE=""
if [ -n "$SESSION_ID" ]; then
  BASELINE_FILE="$SESS_DIR/$SESSION_ID.baseline"
  ATTEMPTS_FILE="$SESS_DIR/$SESSION_ID.stop_attempts"
fi

# ─── Circuit breaker ─────────────────────────────────────────────────
MAX_ATTEMPTS=2
ATTEMPTS=0
if [ -n "$ATTEMPTS_FILE" ] && [ -f "$ATTEMPTS_FILE" ]; then
  ATTEMPTS=$(cat "$ATTEMPTS_FILE" 2>/dev/null || echo 0)
  [[ "$ATTEMPTS" =~ ^[0-9]+$ ]] || ATTEMPTS=0
fi
if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
  echo "[stop-check] Circuit breaker tripped (${ATTEMPTS} consecutive blocks) — allowing stop. Review uncommitted state manually with: git status" >&2
  exit 0
fi

# ─── Session-scoped dirty delta ──────────────────────────────────────
CURRENT=$(git status --porcelain 2>/dev/null \
  | awk 'substr($0,4) !~ /^\.claude\// { print }' \
  | LC_ALL=C sort)

if [ -z "$BASELINE_FILE" ] || [ ! -f "$BASELINE_FILE" ]; then
  # No baseline = can't attribute dirt to this session. Two cases:
  #   1) Session started before session-baseline.sh was installed
  #   2) Hook didn't run for some reason
  # Safest: allow stop. The whole point of session-scoped check is to avoid
  # blocking on state we can't attribute to this session.
  if [ -n "$CURRENT" ]; then
    echo "[stop-check] No session baseline (session_id=${SESSION_ID:-unknown}) — cannot attribute dirty state to this session; allowing stop. Run git status to review." >&2
  fi
  exit 0
fi

# LC_ALL=C: both inputs were sorted under C collation (session-baseline.sh and
# CURRENT above); comm under a UTF-8 locale rejects C-sorted input as unsorted.
NEW_DIRTY=$(LC_ALL=C comm -13 "$BASELINE_FILE" <(echo "$CURRENT"))

# ─── Are subagents still writing? ────────────────────────────────────
# A session running a Workflow fan-out has agents editing the tree right now.
# Every uncommitted file at that moment belongs to an agent mid-task, and
# committing it would capture half-finished work — so the correct response to
# this hook is always "no", and it will fire again on the next turn, and again.
# The 2026-09-02 audit session took 76 such interrupts while ten agents ran,
# refused all 76, and the only thing they produced was noise. A gate that is
# right to ignore teaches people to ignore gates.
#
# Liveness is read off the agents' own transcripts: they append continuously
# while running, so a recent mtime means work is in flight. Override the window
# with STOP_CHECK_AGENT_IDLE_S; 0 disables the check entirely.
_subagents_live() {
  local window="${STOP_CHECK_AGENT_IDLE_S:-180}"
  [ "$window" -gt 0 ] 2>/dev/null || return 1
  [ -n "$SESSION_ID" ] || return 1
  local now mtime f
  now=$(date +%s)
  for f in "$HOME"/.claude/projects/*/"$SESSION_ID"/subagents/*/*/agent-*.jsonl \
           "$HOME"/.claude/projects/*/"$SESSION_ID"/subagents/agent-*.jsonl \
           "$HOME"/.claude-profiles/*/projects/*/"$SESSION_ID"/subagents/*/*/agent-*.jsonl \
           "$HOME"/.claude-profiles/*/projects/*/"$SESSION_ID"/subagents/agent-*.jsonl; do
    [ -f "$f" ] || continue
    mtime=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0)
    # Early return: one live agent is enough, and a long session can hold
    # hundreds of these files against a 10s hook timeout.
    if [ $(( now - mtime )) -lt "$window" ]; then
      return 0
    fi
  done
  return 1
}

if _subagents_live; then
  echo "[stop-check] Subagents are still writing — not flagging uncommitted state." >&2
  echo "             Their files are theirs until they return; commit after they do." >&2
  exit 0
fi

# ─── Build issue list ────────────────────────────────────────────────
issues=()

if [ -n "$NEW_DIRTY" ]; then
  COUNT=$(echo "$NEW_DIRTY" | wc -l | tr -d '[:space:]')
  issues+=("${COUNT} uncommitted change(s) produced this session:")
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    issues+=("    ${line}")
  done < <(echo "$NEW_DIRTY" | head -10)
  EXTRA=$(( COUNT - 10 ))
  [ "$EXTRA" -gt 0 ] && issues+=("    ... and ${EXTRA} more")
fi

# Blockers: only flag if modified AFTER baseline was captured
BLOCKER_FILE=".claude/blockers.md"
if [ -f "$BLOCKER_FILE" ]; then
  BLOCKER_MTIME=$(stat -c %Y "$BLOCKER_FILE" 2>/dev/null || stat -f %m "$BLOCKER_FILE" 2>/dev/null || echo 0)
  BASELINE_MTIME=$(stat -c %Y "$BASELINE_FILE" 2>/dev/null || stat -f %m "$BASELINE_FILE" 2>/dev/null || echo 0)
  if [ "$BLOCKER_MTIME" -gt "$BASELINE_MTIME" ]; then
    BLOCKER_COUNT=$(grep -c "^## Blocker" "$BLOCKER_FILE" 2>/dev/null || echo 0)
    if [ "${BLOCKER_COUNT:-0}" -gt 0 ]; then
      issues+=("${BLOCKER_COUNT} blocker(s) recorded this session in .claude/blockers.md")
    fi
  fi
fi

# ─── Decide ──────────────────────────────────────────────────────────
if [ ${#issues[@]} -gt 0 ]; then
  # If stop_hook_active is already true, Claude Code is retrying after a
  # prior block. Don't block again — escape the loop.
  if [ "$STOP_ACTIVE" = "true" ]; then
    echo "[stop-check] Stop already retried once (stop_hook_active=true) — allowing stop despite remaining issues:" >&2
    for issue in "${issues[@]}"; do
      echo "  - $issue" >&2
    done
    [ -n "$ATTEMPTS_FILE" ] && rm -f "$ATTEMPTS_FILE" 2>/dev/null || true
    exit 0
  fi

  ATTEMPTS=$((ATTEMPTS + 1))
  if [ -n "$ATTEMPTS_FILE" ]; then
    echo "$ATTEMPTS" > "$ATTEMPTS_FILE" 2>/dev/null || true
  fi
  echo "[stop-check] Session not clean (attempt ${ATTEMPTS}/${MAX_ATTEMPTS}):" >&2
  for issue in "${issues[@]}"; do
    echo "  - $issue" >&2
  done
  exit 2
fi

# Clean stop — reset attempt counter
[ -n "$ATTEMPTS_FILE" ] && rm -f "$ATTEMPTS_FILE" 2>/dev/null || true
exit 0
