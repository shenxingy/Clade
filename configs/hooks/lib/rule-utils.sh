#!/usr/bin/env bash
# rule-utils.sh — Shared functions for parsing and manipulating rules.md
# Source this file, then call functions as needed.
#
# Usage:
#   source "$LIBDIR/rule-utils.sh"
#   count_rules "$RULES_FILE"     # → sets RULE_COUNT
#   parse_rules "$RULES_FILE"     # → populates RULE_DATES[], RULE_DOMAINS[], RULE_TEXTS[]

# ─── count_rules ─────────────────────────────────────────────────────
# Count non-empty, non-comment lines starting with "- ["
count_rules() {
  local file="${1:-}"
  RULE_COUNT=0
  [[ -f "$file" ]] || return
  RULE_COUNT=$(grep -c '^- \[' "$file" 2>/dev/null || echo 0)
}

# ─── parse_rules ─────────────────────────────────────────────────────
# Populate parallel arrays: RULE_DATES[], RULE_DOMAINS[], RULE_ROOT_CAUSES[], RULE_TEXTS[], RULE_LINES[]
parse_rules() {
  local file="${1:-}"
  RULE_DATES=()
  RULE_DOMAINS=()
  RULE_ROOT_CAUSES=()
  RULE_TEXTS=()
  RULE_LINES=()

  [[ -f "$file" ]] || return

  while IFS= read -r line; do
    # Format: - [YYYY-MM-DD] domain (root-cause): text
    if [[ "$line" =~ ^-\ \[([0-9]{4}-[0-9]{2}-[0-9]{2})\]\ ([a-zA-Z0-9_-]+)\ \(([a-zA-Z0-9_-]+)\):\ (.+)$ ]]; then
      RULE_DATES+=("${BASH_REMATCH[1]}")
      RULE_DOMAINS+=("${BASH_REMATCH[2]}")
      RULE_ROOT_CAUSES+=("${BASH_REMATCH[3]}")
      RULE_TEXTS+=("${BASH_REMATCH[4]}")
      RULE_LINES+=("$line")
    fi
  done < "$file"
}

# ─── rule_age_days ───────────────────────────────────────────────────
# Given a date string YYYY-MM-DD, return days since that date
rule_age_days() {
  local date_str="${1:-}"
  local now_epoch
  now_epoch=$(date +%s)

  # Cross-platform date parsing
  local rule_epoch
  rule_epoch=$(date -d "$date_str" +%s 2>/dev/null \
            || date -j -f "%Y-%m-%d" "$date_str" +%s 2>/dev/null \
            || echo 0)

  if [[ "$rule_epoch" -eq 0 ]]; then
    echo 999
    return
  fi

  echo $(( (now_epoch - rule_epoch) / 86400 ))
}

# ─── rule_hash ───────────────────────────────────────────────────────
# Generate a short hash of rule text for dedup
rule_hash() {
  local text="${1:-}"
  echo -n "$text" | shasum -a 256 2>/dev/null | cut -c1-8
}

# ─── rule_exists_in_file ────────────────────────────────────────────
# Check if a rule's key text (first 60 chars, normalized) exists in target file
rule_exists_in_file() {
  local rule_text="${1:-}"
  local target_file="${2:-}"

  [[ -f "$target_file" ]] || return 1

  # Normalize: lowercase, collapse whitespace, take first 60 chars
  local needle
  needle=$(echo "$rule_text" | tr '[:upper:]' '[:lower:]' | tr -s ' ' | cut -c1-60)

  local haystack
  haystack=$(tr '[:upper:]' '[:lower:]' < "$target_file" | tr -s ' ')

  echo "$haystack" | grep -qF "$needle" 2>/dev/null
}
