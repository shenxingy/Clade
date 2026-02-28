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
source "$LIBDIR/domain-detect.sh"

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# ─── Read adaptive thresholds ────────────────────────────────────────

STATS_FILE="$HOME/.claude/corrections/stats.json"
STRICT_MODE=false

if [[ -f "$STATS_FILE" ]] && command -v jq &>/dev/null; then
  detect_domain

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

# Track commit granularity stats (non-blocking)
_track_commit_granularity() {
  local files_changed commits_made ratio stats_file
  files_changed=$(git diff --name-only HEAD~1 HEAD 2>/dev/null | wc -l | tr -d ' ')
  commits_made=$(git log --oneline --since="1 hour ago" 2>/dev/null | wc -l | tr -d ' ')
  [[ "$files_changed" -eq 0 ]] && return 0
  ratio=$(echo "scale=2; $commits_made / $files_changed" | bc 2>/dev/null || echo "0")
  stats_file="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/stats.jsonl"
  mkdir -p "$(dirname "$stats_file")"
  echo "{\"date\":\"$(date -Iseconds)\",\"commits\":$commits_made,\"files\":$files_changed,\"ratio\":$ratio}" >> "$stats_file"
}
( _track_commit_granularity ) &

exit $?
