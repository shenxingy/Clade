#!/usr/bin/env bash
# rule-effectiveness.sh — Track hit/miss rates for correction rules
# Source this file, then call functions as needed.
#
# Data stored in ~/.claude/corrections/rule-effectiveness.json
# Format: {"rule_hash": {"hits": N, "misses": N, "last_event": "ISO8601"}}

EFFECTIVENESS_FILE="$HOME/.claude/corrections/rule-effectiveness.json"

_ensure_effectiveness_file() {
  mkdir -p "$(dirname "$EFFECTIVENESS_FILE")"
  [[ -f "$EFFECTIVENESS_FILE" ]] || echo '{}' > "$EFFECTIVENESS_FILE"
}

# ─── record_rule_miss ────────────────────────────────────────────────
# A correction happened in a domain where a rule exists → rule didn't prevent it
record_rule_miss() {
  local hash="${1:-}"
  [[ -z "$hash" ]] && return
  _ensure_effectiveness_file

  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local tmp
  tmp=$(mktemp)

  jq --arg h "$hash" --arg ts "$ts" '
    .[$h] = (.[$h] // {hits:0, misses:0}) |
    .[$h].misses += 1 |
    .[$h].last_event = $ts
  ' "$EFFECTIVENESS_FILE" > "$tmp" 2>/dev/null \
    && mv "$tmp" "$EFFECTIVENESS_FILE" \
    || rm -f "$tmp"
}

# ─── record_rule_hit ─────────────────────────────────────────────────
# Session completed with no corrections in a domain where a rule exists → rule is working
record_rule_hit() {
  local hash="${1:-}"
  [[ -z "$hash" ]] && return
  _ensure_effectiveness_file

  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local tmp
  tmp=$(mktemp)

  jq --arg h "$hash" --arg ts "$ts" '
    .[$h] = (.[$h] // {hits:0, misses:0}) |
    .[$h].hits += 1 |
    .[$h].last_event = $ts
  ' "$EFFECTIVENESS_FILE" > "$tmp" 2>/dev/null \
    && mv "$tmp" "$EFFECTIVENESS_FILE" \
    || rm -f "$tmp"
}

# ─── get_ineffective_rules ──────────────────────────────────────────
# Return rule hashes where miss_rate > 60% and total events >= 3
# Output: one hash per line
get_ineffective_rules() {
  _ensure_effectiveness_file

  jq -r '
    to_entries[] |
    select((.value.hits + .value.misses) >= 3) |
    select((.value.misses / (.value.hits + .value.misses)) > 0.6) |
    .key
  ' "$EFFECTIVENESS_FILE" 2>/dev/null
}

# ─── get_effective_rules ────────────────────────────────────────────
# Return rule hashes where hit_rate >= 70% and total events >= 3
# Output: one hash per line
get_effective_rules() {
  _ensure_effectiveness_file

  jq -r '
    to_entries[] |
    select((.value.hits + .value.misses) >= 3) |
    select((.value.hits / (.value.hits + .value.misses)) >= 0.7) |
    .key
  ' "$EFFECTIVENESS_FILE" 2>/dev/null
}
