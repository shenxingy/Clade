#!/usr/bin/env bash
# rule-cluster.sh — Group correction rules by domain for generalization
#
# Usage: bash rule-cluster.sh [rules_file]
#
# Reads rules.md, groups by domain tag, and suggests generalizations
# when 3+ rules share the same domain.

set -uo pipefail

RULES_FILE="${1:-$HOME/.claude/corrections/rules.md}"

if [[ ! -f "$RULES_FILE" ]]; then
  echo "No rules file found at $RULES_FILE"
  exit 0
fi

# Extract domain tags from rules (format: - [date] domain (root-cause): ...)
declare -A DOMAIN_COUNTS
declare -A DOMAIN_RULES

while IFS= read -r line; do
  # Match: - [YYYY-MM-DD] domain (root-cause): description
  if [[ "$line" =~ ^-[[:space:]]\[([0-9]{4}-[0-9]{2}-[0-9]{2})\][[:space:]]([a-zA-Z_-]+) ]]; then
    domain="${BASH_REMATCH[2]}"
    DOMAIN_COUNTS[$domain]=$(( ${DOMAIN_COUNTS[$domain]:-0} + 1 ))
    DOMAIN_RULES[$domain]="${DOMAIN_RULES[$domain]:-}
  $line"
  fi
done < "$RULES_FILE"

# Report clusters
HAS_CLUSTERS=false
for domain in "${!DOMAIN_COUNTS[@]}"; do
  count=${DOMAIN_COUNTS[$domain]}
  if [[ $count -ge 3 ]]; then
    HAS_CLUSTERS=true
    echo "Cluster: \"$domain\" ($count rules)"
    echo "${DOMAIN_RULES[$domain]}"
    echo "  → Consider generalizing these into a single principle"
    echo ""
  fi
done

if ! $HAS_CLUSTERS; then
  echo "No clusters found (need 3+ rules with same domain tag to suggest generalization)"
fi
