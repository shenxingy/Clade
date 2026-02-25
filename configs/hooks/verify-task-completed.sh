#!/usr/bin/env bash
# verify-task-completed.sh — Adaptive quality gate before marking a task as completed
# Triggered by TaskCompleted
# Exit 2 = block completion, exit 0 = allow
#
# Reads ~/.claude/corrections/stats.json for error rates per domain.
# High error rate domains (>0.3) → strict checks (type-check + build/test)
# Low error rate domains (<0.1) → basic checks only
# Default (no stats or medium error rate) → standard checks
#
# Supported: TypeScript, Python, Rust, Go, Swift, Kotlin/Java, LaTeX

LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/typecheck.sh"

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# ─── Read adaptive thresholds ────────────────────────────────────────

STATS_FILE="$HOME/.claude/corrections/stats.json"
STRICT_MODE=false

if [[ -f "$STATS_FILE" ]] && command -v jq &>/dev/null; then
  # Determine domain from changed files
  CHANGED_FILES=$(git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null || git diff --name-only --cached 2>/dev/null || echo "")

  # Categorize domain
  DOMAIN="unknown"
  if echo "$CHANGED_FILES" | grep -qE '\.(tsx?|jsx?)$'; then
    DOMAIN="frontend"
  elif echo "$CHANGED_FILES" | grep -qE '\.(py|ipynb)$'; then
    if echo "$CHANGED_FILES" | grep -qE 'train|model|dataset|experiment|notebook'; then
      DOMAIN="ml"
    else
      DOMAIN="backend"
    fi
  elif echo "$CHANGED_FILES" | grep -qE 'schema|migration|drizzle|prisma'; then
    DOMAIN="schema"
  elif echo "$CHANGED_FILES" | grep -qE '\.swift$|\.xib$|\.storyboard$|Podfile|\.xcodeproj'; then
    DOMAIN="ios"
  elif echo "$CHANGED_FILES" | grep -qE '\.(kt|java)$|\.gradle'; then
    DOMAIN="android"
  elif echo "$CHANGED_FILES" | grep -qE '\.rs$'; then
    DOMAIN="systems"
  elif echo "$CHANGED_FILES" | grep -qE '\.go$'; then
    DOMAIN="systems"
  elif echo "$CHANGED_FILES" | grep -qE '\.tex$|\.bib$'; then
    DOMAIN="academic"
  fi

  # Read error rate for this domain
  ERROR_RATE=$(jq -r --arg d "$DOMAIN" '.[$d] // 0' "$STATS_FILE" 2>/dev/null)

  if [[ -n "$ERROR_RATE" ]]; then
    IS_HIGH=$(awk "BEGIN {print ($ERROR_RATE > 0.3) ? 1 : 0}")
    IS_LOW=$(awk "BEGIN {print ($ERROR_RATE < 0.1) ? 1 : 0}")

    if [[ "$IS_HIGH" -eq 1 ]]; then
      STRICT_MODE=true
    elif [[ "$IS_LOW" -eq 1 ]]; then
      :
    fi
  fi
fi

# ─── Run project-level type checks ───────────────────────────────────

if $STRICT_MODE; then
  echo "High error rate detected for $DOMAIN — running stricter checks..." >&2
fi

run_typecheck_for_project "$(pwd)" "$STRICT_MODE"
exit $?
