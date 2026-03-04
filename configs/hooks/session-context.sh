#!/usr/bin/env bash
# session-context.sh — Auto-load project context at session start
# Triggered by SessionStart

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# Only run for git repos
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

CONTEXT=""

# ─── Auto-pull from remote ────────────────────────────────────────────
# Only pull if: tracking branch exists, working tree is clean, and remote has new commits
TRACKING=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null)
if [[ -n "$TRACKING" ]]; then
  git fetch --quiet 2>/dev/null
  BEHIND=$(git rev-list HEAD..@{u} --count 2>/dev/null)
  DIRTY=$(git status --short 2>/dev/null)

  if [[ "${BEHIND:-0}" -gt 0 ]]; then
    if [[ -z "$DIRTY" ]]; then
      PULL_OUT=$(git pull --ff-only 2>&1)
      CONTEXT="${CONTEXT}Auto-pulled ${BEHIND} new commit(s) from ${TRACKING}:\n${PULL_OUT}\n\n"
    else
      CONTEXT="${CONTEXT}WARNING: Remote has ${BEHIND} new commit(s) but working tree is dirty — skipped auto-pull. Consider pulling manually after stashing or committing.\n\n"
    fi
  fi
fi

# Recent commits
GIT_LOG=$(git log --oneline -5 2>/dev/null)
if [[ -n "$GIT_LOG" ]]; then
  CONTEXT="Recent commits:\n${GIT_LOG}\n\n"
fi

# Loop state (if active)
if [[ -f ".claude/loop-state" ]]; then
  CONVERGED=$(grep "^CONVERGED=" .claude/loop-state | cut -d= -f2)
  ITERATION=$(grep "^ITERATION=" .claude/loop-state | cut -d= -f2)
  GOAL=$(grep "^GOAL=" .claude/loop-state | cut -d= -f2 | xargs basename 2>/dev/null)
  if [[ "$CONVERGED" == "true" ]]; then
    CONTEXT="${CONTEXT}Loop: ✓ converged (${GOAL}, iter ${ITERATION})\n"
  elif [[ "$CONVERGED" == "false" ]]; then
    CONTEXT="${CONTEXT}Loop: ⟳ running (${GOAL}, iter ${ITERATION})\n"
  fi
fi

# Next TODO item
NEXT_TODO=$(grep -m1 "^\- \[ \]" TODO.md 2>/dev/null | sed 's/- \[ \] \*\*//' | sed 's/\*\*.*//' | xargs)
if [[ -n "$NEXT_TODO" ]]; then
  CONTEXT="${CONTEXT}\nNext TODO: ${NEXT_TODO}\n"
fi

# Uncommitted changes
GIT_STATUS=$(git status --short 2>/dev/null | head -15)
if [[ -n "$GIT_STATUS" ]]; then
  CONTEXT="${CONTEXT}Uncommitted changes:\n${GIT_STATUS}\n\n"
fi

# Current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [[ -n "$BRANCH" ]]; then
  CONTEXT="${CONTEXT}Branch: ${BRANCH}\n"
fi

# Running docker containers (if docker is available)
if command -v docker &>/dev/null; then
  DOCKER=$(docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null | head -5)
  if [[ -n "$DOCKER" ]]; then
    CONTEXT="${CONTEXT}\nRunning containers:\n${DOCKER}"
  fi
fi

# Auto-load latest handoff file (< 24h old)
HANDOFF_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude"
if [[ -d "$HANDOFF_DIR" ]]; then
  LATEST_HANDOFF=$(ls -t "$HANDOFF_DIR"/handoff-*.md 2>/dev/null | head -1)
  if [[ -n "$LATEST_HANDOFF" && -f "$LATEST_HANDOFF" ]]; then
    FILE_MTIME=$(stat -c %Y "$LATEST_HANDOFF" 2>/dev/null || stat -f %m "$LATEST_HANDOFF" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    AGE_HOURS=$(( (NOW - FILE_MTIME) / 3600 ))
    if [[ $AGE_HOURS -lt 24 ]]; then
      HANDOFF_CONTENT=$(cat "$LATEST_HANDOFF" 2>/dev/null)
      CONTEXT="${CONTEXT}\n## Handoff from previous session (${AGE_HOURS}h ago)\n${HANDOFF_CONTENT}\nRun /pickup to resume from this handoff.\n"
    fi
  fi
fi

# Load correction rules (learned preferences)
RULES_FILE="$HOME/.claude/corrections/rules.md"
if [[ -f "$RULES_FILE" ]]; then
  RULES=$(tail -50 "$RULES_FILE" 2>/dev/null)
  if [[ -n "$RULES" ]]; then
    CONTEXT="${CONTEXT}\nCorrection rules (learned from past feedback):\n${RULES}\n"
  fi
fi

# Audit nudge (if corrections haven't been audited in 7+ days)
LAST_AUDIT_FILE="$HOME/.claude/corrections/.last-audit"
if [[ -f "$LAST_AUDIT_FILE" ]]; then
  AUDIT_MTIME=$(stat -c %Y "$LAST_AUDIT_FILE" 2>/dev/null || stat -f %m "$LAST_AUDIT_FILE" 2>/dev/null || echo 0)
  AUDIT_AGE_DAYS=$(( ($(date +%s) - AUDIT_MTIME) / 86400 ))
else
  AUDIT_AGE_DAYS=999
fi
if [[ $AUDIT_AGE_DAYS -ge 7 ]]; then
  CONTEXT="${CONTEXT}\nAudit reminder: Correction rules haven't been audited in ${AUDIT_AGE_DAYS}+ days. Run /audit to graduate mature rules to CLAUDE.md and clean up stale ones.\n"
fi

# Language constraint
CONTEXT="${CONTEXT}\nIMPORTANT: Always respond in the same language the user writes in. If the user writes Chinese, respond in Chinese. If English, respond in English. NEVER respond in Korean under any circumstances.\n"

# Model selection guidance
CONTEXT="${CONTEXT}\nModel guide: Sonnet 4.6 is optimal for most coding (79.6% SWE-bench, 40% cheaper than Opus). Switch to Opus 4.6 only for: large refactors (10+ files), deep architectural reasoning, or outputs >64K tokens. Use Haiku 4.5 for sub-agents doing mechanical checks. If you detect the user is about to do a complex multi-file refactor on Sonnet, suggest: 'This task may benefit from Opus — run /model to switch.'\n"

# Stale kit detection
KIT_SOURCE_FILE="$HOME/.claude/.kit-source-dir"
KIT_CHECKSUM_FILE="$HOME/.claude/.kit-checksum"
if [[ -f "$KIT_SOURCE_FILE" && -f "$KIT_CHECKSUM_FILE" ]]; then
  _KIT_DIR=$(cat "$KIT_SOURCE_FILE")
  if [[ -d "$_KIT_DIR/configs" ]]; then
    _CURRENT=$(find "$_KIT_DIR/configs" -type f | LC_ALL=C sort | xargs sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1)
    _INSTALLED=$(cat "$KIT_CHECKSUM_FILE")
    if [[ "$_CURRENT" != "$_INSTALLED" ]]; then
      CONTEXT="${CONTEXT}\n⚠ STALE KIT: configs/ changed since last install.sh — run: cd $_KIT_DIR && ./install.sh\n"
    fi
  fi
fi

# Revert rate check
REVERT_COUNT=$(git log --oneline --since="7 days ago" --grep="^Revert" 2>/dev/null | wc -l | tr -d ' ')
TOTAL_COUNT=$(git log --oneline --since="7 days ago" 2>/dev/null | wc -l | tr -d ' ')
if [[ "${TOTAL_COUNT:-0}" -gt 10 && "${REVERT_COUNT:-0}" -gt 0 ]]; then
  REVERT_RATE=$(( REVERT_COUNT * 100 / TOTAL_COUNT ))
  if [[ "$REVERT_RATE" -gt 10 ]]; then
    CONTEXT="${CONTEXT}\n⚠ High revert rate this week: ${REVERT_COUNT}/${TOTAL_COUNT} commits (${REVERT_RATE}%)\n"
  fi
fi

if [[ -n "$CONTEXT" ]]; then
  jq -n --arg ctx "$CONTEXT" \
    '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'
fi

exit 0
