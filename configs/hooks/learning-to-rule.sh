#!/usr/bin/env bash
# learning-to-rule.sh — Convert high-confidence learnings to rule candidates
#
# Called from session-context.sh at session start.
# Reads .claude/learnings.jsonl (project-local), finds entries with:
#   - confidence >= 80 (single occurrence is enough)
#   - OR same content fingerprint appears 2+ times (any confidence)
# Converts qualifying entries to rules.md candidates.
#
# Usage: source learning-to-rule.sh && run_learning_promotion [project_dir]

LIBDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
source "$LIBDIR/rule-utils.sh" 2>/dev/null

run_learning_promotion() {
  local project_dir="${1:-$(pwd)}"
  LEARNING_SUMMARY=""

  # Check both project-local and global learnings
  local learnings_files=()
  [[ -f "$project_dir/.claude/learnings.jsonl" ]] && learnings_files+=("$project_dir/.claude/learnings.jsonl")
  [[ -f "$HOME/.claude/learnings.jsonl" ]] && learnings_files+=("$HOME/.claude/learnings.jsonl")

  [[ ${#learnings_files[@]} -eq 0 ]] && return 0

  command -v jq &>/dev/null || return 0

  # Determine target rules.md
  local rules_file rules_limit
  if [[ -d "$project_dir/.git" || -f "$project_dir/CLAUDE.md" ]]; then
    rules_file="$project_dir/.claude/corrections/rules.md"
    rules_limit=100
  else
    rules_file="$HOME/.claude/corrections/rules.md"
    rules_limit=50
  fi
  mkdir -p "$(dirname "$rules_file")"
  [[ -f "$rules_file" ]] || echo "# Correction Rules" > "$rules_file"

  local promoted=0
  local today
  today=$(date +%Y-%m-%d)

  for lfile in "${learnings_files[@]}"; do
    # Extract qualifying learnings: confidence >= 80 AND not pruned AND not already promoted
    local candidates
    candidates=$(jq -c '
      select(.pruned != true) |
      select(.promoted_to_rule != true) |
      select(.confidence >= 80) |
      select((.content | length) >= 30)
    ' "$lfile" 2>/dev/null)

    [[ -z "$candidates" ]] && continue

    while IFS= read -r entry; do
      [[ -z "$entry" ]] && continue

      local content type confidence id
      content=$(echo "$entry" | jq -r '.content')
      type=$(echo "$entry" | jq -r '.type // "pattern"')
      confidence=$(echo "$entry" | jq -r '.confidence // 75')
      id=$(echo "$entry" | jq -r '.id // "unknown"')

      # Map learning type to rule domain
      local domain
      case "$type" in
        pitfall)      domain="workflow" ;;
        preference)   domain="workflow" ;;
        architecture) domain="architecture" ;;
        tool)         domain="tooling" ;;
        *)            domain="general" ;;
      esac

      # Check dedup: skip if rule text already exists in rules.md
      if rule_exists_in_file "$content" "$rules_file"; then
        continue
      fi

      # Check rules.md line count
      count_rules "$rules_file"
      if [[ "$RULE_COUNT" -ge "$rules_limit" ]]; then
        break 2
      fi

      # Append as rule candidate
      printf '- [%s] %s (learning): %s\n' "$today" "$domain" "$content" >> "$rules_file"
      promoted=$((promoted + 1))

      # Mark learning as promoted (in-place update)
      local tmp
      tmp=$(mktemp)
      jq -c --arg id "$id" '
        if .id == $id then .promoted_to_rule = true else . end
      ' "$lfile" > "$tmp" 2>/dev/null && mv "$tmp" "$lfile" || rm -f "$tmp"

    done <<< "$candidates"
  done

  # Also check for duplicate learnings (same content across 2+ entries, any confidence)
  for lfile in "${learnings_files[@]}"; do
    local dupes
    dupes=$(jq -c 'select(.pruned != true) | select(.promoted_to_rule != true) | .content' "$lfile" 2>/dev/null \
      | sort | uniq -c | sort -rn \
      | awk '$1 >= 2 {$1=""; print substr($0,2)}' \
      | head -5)

    while IFS= read -r dup_content; do
      [[ -z "$dup_content" ]] && continue
      # Remove surrounding quotes from jq output
      dup_content=$(echo "$dup_content" | sed 's/^"//; s/"$//')

      [[ ${#dup_content} -lt 30 ]] && continue

      if rule_exists_in_file "$dup_content" "$rules_file"; then
        continue
      fi

      count_rules "$rules_file"
      [[ "$RULE_COUNT" -ge "$rules_limit" ]] && break 2

      printf '- [%s] general (learning-repeated): %s\n' "$today" "$dup_content" >> "$rules_file"
      promoted=$((promoted + 1))
    done <<< "$dupes"
  done

  if [[ "$promoted" -gt 0 ]]; then
    LEARNING_SUMMARY="Learning→Rule: promoted ${promoted} high-confidence learning(s) to rules.md"
  fi
}
