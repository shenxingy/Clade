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
  echo -n "$text" | { command -v sha256sum >/dev/null 2>&1 && sha256sum || shasum -a 256; } 2>/dev/null | cut -c1-8
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

# ─── rule_earns_promotion ────────────────────────────────────────────
# Does this root cause justify permanent CLAUDE.md context?
#
# CLAUDE.md loads on every session, so a line there is a standing tax on every
# future turn. Only failure classes that cause real damage — silent breakage,
# data races, leaked secrets, shipped-but-not-running code — clear that bar.
#
# `edge-case` is deliberately excluded despite being the most COMMON class:
# common is not the same as costly, and promoting on frequency is how the file
# filled with 28 of them. They remain in rules.md, where `/audit` promotes them
# by human judgement rather than by having survived a fortnight.
# Matched with `case` rather than by splitting a string on spaces: zsh does not
# word-split unquoted parameters, so the loop form silently withheld EVERY rule
# when this lib was sourced from a zsh shell.
#
# The collaboration classes were added after Tang et al. 2026 (arXiv:2605.29442,
# 16,118 evidence-grounded episodes from 20,574 real sessions) measured what
# actually goes wrong between developers and coding agents. Two of their seven
# symptoms dominate and are GROWING in share over time:
#   Developer Constraint Violation  38.33%   (highest in CLI: 49.49%)
#   Inaccurate Self-Reporting       22.58%
# Both cost trust rather than data, which is precisely why they were invisible
# to a taxonomy built only from defect classes: a correction about either one
# had nowhere to go except `edge-case`, the bucket this gate withholds. The
# most common real-world failure was being systematically suppressed.
RULE_PROMOTABLE_ROOT_CAUSES="security async-race deploy-gap settings-disconnect data-loss inaccurate-self-reporting constraint-violation"

rule_earns_promotion() {
  case "${1:-}" in
    security|async-race|deploy-gap|settings-disconnect|data-loss) return 0 ;;
    inaccurate-self-reporting|constraint-violation) return 0 ;;
    *) return 1 ;;
  esac
}
