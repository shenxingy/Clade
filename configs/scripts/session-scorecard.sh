#!/usr/bin/env bash
# session-scorecard.sh — Generate session metrics and append to scorecards.jsonl
#
# Usage: bash session-scorecard.sh
#
# Reads correction history, git log, and computes a session quality score.
# Appends one JSON line to ~/.claude/corrections/scorecards.jsonl
#
# Called by /sync skill at session end.

set -uo pipefail

CORRECTIONS_DIR="$HOME/.claude/corrections"
HISTORY_FILE="$CORRECTIONS_DIR/history.jsonl"
SCORECARDS_FILE="$CORRECTIONS_DIR/scorecards.jsonl"

mkdir -p "$CORRECTIONS_DIR"

# ─── Determine session window (last 4 hours or since last scorecard) ──
LAST_SCORECARD_TS=""
if [[ -f "$SCORECARDS_FILE" ]]; then
  # Slurp, not `tail -1`: this file's own writer was `jq -n` (pretty-printed)
  # until 2026-09, so despite the .jsonl name a legacy record spans 10 lines and
  # `tail -1` yields the single character `}`. `jq` then failed on every run,
  # LAST_SCORECARD_TS was always empty, and SINCE always fell back to the 4-hour
  # default below — the window never advanced. Slurping reads both the legacy
  # pretty records and the compact ones the fixed writer now emits.
  LAST_SCORECARD_TS=$(jq -rs 'map(.timestamp? // empty) | last // empty' \
                        "$SCORECARDS_FILE" 2>/dev/null)
fi

if [[ -n "$LAST_SCORECARD_TS" ]]; then
  SINCE="$LAST_SCORECARD_TS"
else
  # Default: last 4 hours
  SINCE=$(date -u -d '4 hours ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
       || date -u -v-4H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
       || echo "2000-01-01T00:00:00Z")
fi

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ─── Count corrections in this session ────────────────────────────────
EXPLICIT_CORRECTIONS=0
IMPLICIT_CORRECTIONS=0

# Why jq and not awk: the previous implementation matched the timestamp with a
# 3-argument `match(line, /re/, arr)`, which is a GAWK EXTENSION. mawk — the
# default awk on Debian/Ubuntu, i.e. the machines this repo runs on — and BSD awk
# both reject it outright ("syntax error", exit 2), and the `2>/dev/null || echo 0`
# fallback converted that error into a plausible zero. Both counters were
# structurally 0 for the life of the file. The hand-rolled regex was also
# spacing-sensitive: it matched `"timestamp":"..."` but not the `"timestamp": "..."`
# form, which is the majority of the records actually on disk. jq is already a hard
# dependency of this script (window reader, domains, writer) and has neither
# problem. Do NOT "simplify" this back to awk.
#
# `jq -R` + `fromjson?` keeps the parse LINE-SCOPED on purpose: history.jsonl has
# been corrupted by interleaved concurrent appends before (see the header of
# configs/hooks/lib/correction-pair.sh), and a whole-stream parse aborts at the
# first bad byte and silently loses every record after it. The old awk was immune
# to that because it was line-scoped; this keeps that property.
_classify_corrections() {
  jq -rR --arg since "$1" '
    fromjson? // empty
    | select((.timestamp // "") >= $since)
    | if ((.type // "") | startswith("implicit")) then "implicit" else "explicit" end
  ' "$HISTORY_FILE" 2>/dev/null
}

if [[ -f "$HISTORY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  _kinds=$(_classify_corrections "$SINCE")
  # grep -c exits 1 on no match; `|| true` keeps the substitution's value at "0"
  # so the --argjson below stays valid JSON.
  EXPLICIT_CORRECTIONS=$(printf '%s\n' "$_kinds" | grep -c '^explicit$' || true)
  IMPLICIT_CORRECTIONS=$(printf '%s\n' "$_kinds" | grep -c '^implicit$' || true)
fi

# ─── Count commits and reverts in this session ────────────────────────
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || true

COMMITS_COUNT=0
REVERTS_COUNT=0
if git rev-parse --is-inside-work-tree &>/dev/null; then
  COMMITS_COUNT=$(git log --oneline --since="$SINCE" 2>/dev/null | wc -l | tr -d ' ')
  REVERTS_COUNT=$(git log --oneline --since="$SINCE" --grep="revert" -i 2>/dev/null | wc -l | tr -d ' ')
fi

# ─── Compute score (0.0 - 1.0) ───────────────────────────────────────
# Score = 1.0 - penalties
# Penalty: -0.1 per explicit correction, -0.05 per implicit, -0.15 per revert
TOTAL_CORRECTIONS=$((EXPLICIT_CORRECTIONS + IMPLICIT_CORRECTIONS))
PENALTY=$(awk "BEGIN {
  p = ($EXPLICIT_CORRECTIONS * 0.1) + ($IMPLICIT_CORRECTIONS * 0.05) + ($REVERTS_COUNT * 0.15)
  print (p > 1.0) ? 1.0 : p
}")
SCORE=$(awk "BEGIN { printf \"%.2f\", 1.0 - $PENALTY }")

# ─── Rule effectiveness tracking ─────────────────────────────────────
# For domains with rules but no corrections this session → record hits
LIBDIR="$(cd "$(dirname "$0")/../hooks/lib" 2>/dev/null && pwd)"
if [[ -f "$LIBDIR/rule-effectiveness.sh" && -f "$LIBDIR/rule-utils.sh" ]]; then
  source "$LIBDIR/rule-utils.sh" 2>/dev/null
  source "$LIBDIR/rule-effectiveness.sh" 2>/dev/null

  # Get domains that had corrections this session
  CORRECTION_DOMAINS=""
  if [[ -f "$HISTORY_FILE" ]] && command -v jq &>/dev/null; then
    CORRECTION_DOMAINS=$(jq -r --arg since "$SINCE" '
      select(.timestamp >= $since) | .domain // "unknown"
    ' "$HISTORY_FILE" 2>/dev/null | sort -u)
  fi

  # Check rules in both global and project-local
  for rf in "$HOME/.claude/corrections/rules.md" "${CLAUDE_PROJECT_DIR:-.}/.claude/corrections/rules.md"; do
    [[ -f "$rf" ]] || continue
    parse_rules "$rf" 2>/dev/null || continue

    for (( _i=0; _i<${#RULE_DOMAINS[@]}; _i++ )); do
      local_domain="${RULE_DOMAINS[$_i]}"
      local_hash=$(rule_hash "${RULE_TEXTS[$_i]}" 2>/dev/null)
      [[ -z "$local_hash" ]] && continue

      # If this domain had no corrections → rule is working (hit)
      if ! echo "$CORRECTION_DOMAINS" | grep -qF "$local_domain" 2>/dev/null; then
        record_rule_hit "$local_hash" 2>/dev/null
      fi
    done
  done
fi

# ─── Write scorecard ─────────────────────────────────────────────────
# -c is load-bearing: without it this "jsonl" file is pretty-printed and every
# line-oriented reader of it (including the window reader at the top of this
# script) breaks.
jq -nc \
  --arg ts "$NOW" \
  --arg since "$SINCE" \
  --argjson explicit "$EXPLICIT_CORRECTIONS" \
  --argjson implicit "$IMPLICIT_CORRECTIONS" \
  --argjson commits "$COMMITS_COUNT" \
  --argjson reverts "$REVERTS_COUNT" \
  --argjson score "$SCORE" \
  --arg project "${CLAUDE_PROJECT_DIR:-$(pwd)}" \
  '{
    timestamp: $ts,
    since: $since,
    corrections: $explicit,
    implicit_corrections: $implicit,
    commits: $commits,
    reverts: $reverts,
    score: $score,
    project: $project
  }' >> "$SCORECARDS_FILE"

echo "Session scorecard: score=$SCORE corrections=$TOTAL_CORRECTIONS commits=$COMMITS_COUNT"
