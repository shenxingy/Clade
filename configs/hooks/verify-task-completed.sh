#!/usr/bin/env bash
# verify-task-completed.sh — Adaptive quality gate before marking a task as completed
# Triggered by TaskCompleted
# Exit 2 = block completion, exit 0 = allow
#
# Reads ~/.claude/corrections/stats.json for error rates per domain.
# High error rate domains (>0.3) → strict checks (type-check + build)
# Low error rate domains (<0.1) → only type-check
# Default (no stats or medium error rate) → type-check only

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# ─── Read adaptive thresholds ────────────────────────────────────────

STATS_FILE="$HOME/.claude/corrections/stats.json"
STRICT_MODE=false

if [[ -f "$STATS_FILE" ]] && command -v jq &>/dev/null; then
  # Determine domain from changed files
  CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null || git diff --name-only 2>/dev/null)

  # Categorize: frontend, backend, schema, etc.
  DOMAIN="unknown"
  if echo "$CHANGED_FILES" | grep -qE '\.(tsx?|jsx?)$'; then
    DOMAIN="frontend"
  elif echo "$CHANGED_FILES" | grep -qE '\.py$'; then
    DOMAIN="backend"
  elif echo "$CHANGED_FILES" | grep -qE 'schema|migration|drizzle'; then
    DOMAIN="schema"
  fi

  # Read error rate for this domain
  ERROR_RATE=$(jq -r --arg d "$DOMAIN" '.[$d] // 0' "$STATS_FILE" 2>/dev/null)

  if [[ -n "$ERROR_RATE" ]]; then
    # Compare using bc or awk (bash can't do float comparison)
    IS_HIGH=$(awk "BEGIN {print ($ERROR_RATE > 0.3) ? 1 : 0}")
    IS_LOW=$(awk "BEGIN {print ($ERROR_RATE < 0.1) ? 1 : 0}")

    if [[ "$IS_HIGH" -eq 1 ]]; then
      STRICT_MODE=true
    elif [[ "$IS_LOW" -eq 1 ]]; then
      # Low error rate — only run type-check (skip build)
      :
    fi
  fi
fi

# ─── TypeScript project check ────────────────────────────────────────

if [[ -f "pnpm-workspace.yaml" ]]; then
  # Auto-detect package with type-check script
  PKG=$(find apps packages -name package.json -maxdepth 2 2>/dev/null \
    | xargs grep -l '"type-check"' 2>/dev/null | head -1)
  if [[ -n "$PKG" ]]; then
    PKG_NAME=$(jq -r '.name' "$PKG")
    RESULT=$(pnpm --filter "$PKG_NAME" type-check 2>&1)
  else
    RESULT=$(pnpm type-check 2>&1)
  fi
  if [[ $? -ne 0 ]]; then
    echo "Type-check failing. Fix TypeScript errors before completing this task:" >&2
    echo "$RESULT" | tail -15 >&2
    exit 2
  fi

  # Strict mode: also run build
  if $STRICT_MODE; then
    echo "High error rate detected for $DOMAIN — running stricter checks..." >&2
    if [[ -n "$PKG" ]]; then
      BUILD_RESULT=$(pnpm --filter "$PKG_NAME" build 2>&1)
    else
      BUILD_RESULT=$(pnpm build 2>&1)
    fi
    if [[ $? -ne 0 ]]; then
      echo "Build failing (strict mode). Fix build errors before completing this task:" >&2
      echo "$BUILD_RESULT" | tail -20 >&2
      exit 2
    fi
  fi
fi

# ─── Python project check ────────────────────────────────────────────

if [[ -f "pyproject.toml" ]]; then
  if command -v ruff &>/dev/null; then
    RESULT=$(ruff check . 2>&1 | head -20)
    if [[ $? -ne 0 ]]; then
      echo "Ruff lint errors. Fix before completing this task:" >&2
      echo "$RESULT" >&2
      exit 2
    fi
  fi

  # Strict mode: also run mypy
  if $STRICT_MODE && command -v mypy &>/dev/null; then
    echo "High error rate detected for $DOMAIN — running mypy..." >&2
    MYPY_RESULT=$(mypy . 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Mypy errors (strict mode). Fix before completing this task:" >&2
      echo "$MYPY_RESULT" >&2
      exit 2
    fi
  fi
fi

exit 0
