#!/usr/bin/env bash
# contradiction-detect.sh — Detect conflicting rules in the same domain
# Source this file, then call detect_contradictions(rules_file)
#
# Output: CONTRADICTIONS array, each entry is "domain: rule_A vs rule_B"

detect_contradictions() {
  local file="${1:-}"
  CONTRADICTIONS=()

  [[ -f "$file" ]] || return

  # Source rule-utils for parsing
  local LIBDIR
  LIBDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  source "$LIBDIR/rule-utils.sh" 2>/dev/null

  parse_rules "$file"

  local count=${#RULE_DOMAINS[@]}
  [[ "$count" -lt 2 ]] && return

  # Compare same-domain pairs for keyword conflicts
  local i j
  for (( i=0; i<count; i++ )); do
    for (( j=i+1; j<count; j++ )); do
      # Only check same-domain pairs
      [[ "${RULE_DOMAINS[$i]}" != "${RULE_DOMAINS[$j]}" ]] && continue

      local text_a="${RULE_TEXTS[$i]}"
      local text_b="${RULE_TEXTS[$j]}"
      local domain="${RULE_DOMAINS[$i]}"

      # Extract "do this" / "not this" from "do X instead of Y" or "do X — not Y"
      local do_a not_a do_b not_b
      do_a=$(echo "$text_a" | sed -n 's/.*[Uu]se \(.*\) instead of.*/\1/p; s/.*[Dd]o \(.*\) — not.*/\1/p' | head -1)
      not_a=$(echo "$text_a" | sed -n 's/.*instead of \(.*\)/\1/p; s/.*— not \(.*\)/\1/p' | head -1)
      do_b=$(echo "$text_b" | sed -n 's/.*[Uu]se \(.*\) instead of.*/\1/p; s/.*[Dd]o \(.*\) — not.*/\1/p' | head -1)
      not_b=$(echo "$text_b" | sed -n 's/.*instead of \(.*\)/\1/p; s/.*— not \(.*\)/\1/p' | head -1)

      # Check: rule_A recommends X, rule_B says avoid X (or vice versa)
      local conflict=false

      # Direct opposition: A's "do" matches B's "not" (normalized, first 30 chars)
      if [[ -n "$do_a" && -n "$not_b" ]]; then
        local norm_do_a norm_not_b
        norm_do_a=$(echo "$do_a" | tr '[:upper:]' '[:lower:]' | cut -c1-30)
        norm_not_b=$(echo "$not_b" | tr '[:upper:]' '[:lower:]' | cut -c1-30)
        if [[ "$norm_do_a" == "$norm_not_b" ]]; then
          conflict=true
        fi
      fi

      # Reverse: B's "do" matches A's "not"
      if [[ -n "$do_b" && -n "$not_a" ]]; then
        local norm_do_b norm_not_a
        norm_do_b=$(echo "$do_b" | tr '[:upper:]' '[:lower:]' | cut -c1-30)
        norm_not_a=$(echo "$not_a" | tr '[:upper:]' '[:lower:]' | cut -c1-30)
        if [[ "$norm_do_b" == "$norm_not_a" ]]; then
          conflict=true
        fi
      fi

      # "always X" vs "never X" in same domain
      local always_a never_a always_b never_b
      always_a=$(echo "$text_a" | grep -oiE 'always [a-z ]{5,30}' | head -1 | tr '[:upper:]' '[:lower:]')
      never_b=$(echo "$text_b" | grep -oiE 'never [a-z ]{5,30}' | head -1 | tr '[:upper:]' '[:lower:]' | sed 's/^never //')
      if [[ -n "$always_a" && -n "$never_b" ]]; then
        local always_verb
        always_verb=$(echo "$always_a" | sed 's/^always //')
        if [[ "$always_verb" == "$never_b" ]]; then
          conflict=true
        fi
      fi

      if $conflict; then
        CONTRADICTIONS+=("${domain}: [${RULE_DATES[$i]}] vs [${RULE_DATES[$j]}]")
      fi
    done
  done
}
