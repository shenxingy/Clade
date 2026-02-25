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
  LAST_SCORECARD_TS=$(tail -1 "$SCORECARDS_FILE" 2>/dev/null | jq -r '.timestamp // empty' 2>/dev/null)
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

if [[ -f "$HISTORY_FILE" ]]; then
  EXPLICIT_CORRECTIONS=$(awk -v since="$SINCE" '
    { line=$0; match(line, /"timestamp":"([^"]+)"/, ts)
      if (ts[1] >= since) {
        if (line ~ /"type":"implicit/) impl++; else expl++
      }
    }
    END { print expl+0 }
  ' "$HISTORY_FILE" 2>/dev/null || echo 0)

  IMPLICIT_CORRECTIONS=$(awk -v since="$SINCE" '
    { line=$0; match(line, /"timestamp":"([^"]+)"/, ts)
      if (ts[1] >= since && line ~ /"type":"implicit/) count++
    }
    END { print count+0 }
  ' "$HISTORY_FILE" 2>/dev/null || echo 0)
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

# ─── Write scorecard ─────────────────────────────────────────────────
jq -n \
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
