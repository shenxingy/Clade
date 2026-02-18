#!/usr/bin/env bash
# session-context.sh — Auto-load project context at session start
# Triggered by SessionStart

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# Only run for git repos
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

CONTEXT=""

# Recent commits
GIT_LOG=$(git log --oneline -5 2>/dev/null)
if [[ -n "$GIT_LOG" ]]; then
  CONTEXT="Recent commits:\n${GIT_LOG}\n\n"
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

# Load correction rules (learned preferences)
RULES_FILE="$HOME/.claude/corrections/rules.md"
if [[ -f "$RULES_FILE" ]]; then
  RULES=$(tail -30 "$RULES_FILE" 2>/dev/null)
  if [[ -n "$RULES" ]]; then
    CONTEXT="${CONTEXT}\nCorrection rules (learned from past feedback):\n${RULES}\n"
  fi
fi

# Model selection guidance
CONTEXT="${CONTEXT}\nModel guide: Sonnet 4.6 is optimal for most coding (79.6% SWE-bench, 40% cheaper than Opus). Switch to Opus 4.6 only for: large refactors (10+ files), deep architectural reasoning, or outputs >64K tokens. Use Haiku 4.5 for sub-agents doing mechanical checks. If you detect the user is about to do a complex multi-file refactor on Sonnet, suggest: 'This task may benefit from Opus — run /model to switch.'\n"

if [[ -n "$CONTEXT" ]]; then
  jq -n --arg ctx "$CONTEXT" \
    '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'
fi

exit 0
