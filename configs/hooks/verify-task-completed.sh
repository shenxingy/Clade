#!/usr/bin/env bash
# verify-task-completed.sh — Adaptive quality gate before marking a task as completed
# Triggered by TaskCompleted
# Exit 2 = block completion, exit 0 = allow
#
# Reads ~/.claude/corrections/stats.json, which holds per-domain correction
# COUNTS (integers, unbounded) written by correction-detector.sh.
# A domain carrying >=3 corrections and at least half the worst domain's count
#   → strict checks (type-check + build/test)
# Everything else → standard checks
# There is no true error RATE here: nothing records the denominator.
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

  # stats.json holds unbounded COUNTS, not rates. This block used to compare
  # them against 0.3 and 0.1 as if they were fractions, so a domain went strict
  # forever after its first recorded correction (a real file held frontend=17,
  # devops=30) and a domain at 0 stayed relaxed forever. The gate never adapted;
  # it latched.
  #
  # There is no denominator to turn a count into a true error rate — nothing
  # records opportunities. What the counts DO support is a comparison between
  # domains: strict for a domain carrying a meaningful share of this machine's
  # corrections. `unknown` is excluded because it is the unclassified bucket,
  # not a domain, and it dominates every real one.
  DOMAIN_COUNT=$(jq -r --arg d "$DOMAIN" '(.[$d] // 0) | floor' "$STATS_FILE" 2>/dev/null || echo 0)
  PEAK_COUNT=$(jq -r 'del(.unknown) | [.[] | numbers] | (max // 0) | floor' "$STATS_FILE" 2>/dev/null || echo 0)

  # Strict when this domain is at least half as corrected as the worst one, and
  # has enough absolute history for that ratio to mean anything.
  # `unknown` is never strict-eligible either. It is what detect_domain returns
  # when it cannot classify, it outnumbers every real domain (554 vs 30 on this
  # machine), and treating it as a domain would put almost every task in strict
  # mode — the same latch, one level over.
  if [[ "$DOMAIN" != "unknown" && "${DOMAIN_COUNT:-0}" -ge 3 && "${PEAK_COUNT:-0}" -gt 0 ]] \
     && [[ $(( DOMAIN_COUNT * 2 )) -ge "$PEAK_COUNT" ]]; then
    STRICT_MODE=true
  fi
fi

# ─── Run project-level type checks ───────────────────────────────────

if $STRICT_MODE; then
  echo "$DOMAIN carries $DOMAIN_COUNT correction(s), peak $PEAK_COUNT — running stricter checks..." >&2
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
  echo "{\"date\":\"$(date +"%Y-%m-%dT%H:%M:%S%z")\",\"commits\":$commits_made,\"files\":$files_changed,\"ratio\":$ratio}" >> "$stats_file"
}
( _track_commit_granularity ) &

exit $?
