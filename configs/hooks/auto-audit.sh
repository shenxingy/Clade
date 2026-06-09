#!/usr/bin/env bash
# auto-audit.sh — Programmatic rule promotion, archival, and cross-project aggregation
#
# Called from session-context.sh when:
#   1. .last-audit > 7 days old
#   2. rules.md has 10+ rules
#
# This is the deterministic complement to /audit (LLM skill).
# /audit handles: clustering, contradiction resolution, trend analysis
# auto-audit handles: date-based promotion, dedup, archival, cross-project
#
# Usage: source auto-audit.sh && run_auto_audit [scope]
#   scope: "global" (default) or path to project dir

LIBDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
source "$LIBDIR/rule-utils.sh" 2>/dev/null
source "$LIBDIR/rule-effectiveness.sh" 2>/dev/null

run_auto_audit() {
  local scope="${1:-global}"
  local RULES_FILE CLAUDE_TARGET ARCHIVE_FILE LAST_AUDIT_FILE

  if [[ "$scope" == "global" ]]; then
    RULES_FILE="$HOME/.claude/corrections/rules.md"
    CLAUDE_TARGET="$HOME/.claude/CLAUDE.md"
    ARCHIVE_FILE="$HOME/.claude/corrections/rules-archive.md"
    LAST_AUDIT_FILE="$HOME/.claude/corrections/.last-audit"
  else
    RULES_FILE="$scope/.claude/corrections/rules.md"
    CLAUDE_TARGET="$scope/CLAUDE.md"
    ARCHIVE_FILE="$scope/.claude/corrections/rules-archive.md"
    LAST_AUDIT_FILE="$scope/.claude/corrections/.last-audit"
  fi

  [[ -f "$RULES_FILE" ]] || return 0

  # Check preconditions
  count_rules "$RULES_FILE"
  [[ "$RULE_COUNT" -lt 10 ]] && return 0

  # Timer gates PROMOTE/ARCHIVE/cross-project (mutating, churn-prone). REDUNDANT
  # dedup is idempotent cleanup and runs every session regardless — so duplicates
  # leaked by the LLM /audit skill (which promotes to CLAUDE.md but may skip its
  # remove-from-rules.md step) get garbage-collected on the next session instead
  # of lingering up to 7 days until the next promote pass.
  local timer_elapsed=1
  if [[ -f "$LAST_AUDIT_FILE" ]]; then
    local audit_mtime now age_days
    audit_mtime=$(stat -c %Y "$LAST_AUDIT_FILE" 2>/dev/null || stat -f %m "$LAST_AUDIT_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    age_days=$(( (now - audit_mtime) / 86400 ))
    [[ "$age_days" -lt 7 ]] && timer_elapsed=0
  fi

  # Parse all rules
  parse_rules "$RULES_FILE"
  local total=${#RULE_DATES[@]}
  [[ "$total" -eq 0 ]] && return 0

  local promoted=0
  local redundant=0
  local archived=0
  local lines_to_remove=()
  local promoted_names=()
  local archived_names=()

  mkdir -p "$(dirname "$ARCHIVE_FILE")"

  # ─── Process each rule ───────────────────────────────────────────
  local i
  for (( i=0; i<total; i++ )); do
    local age
    age=$(rule_age_days "${RULE_DATES[$i]}")
    local text="${RULE_TEXTS[$i]}"
    local line="${RULE_LINES[$i]}"
    local domain="${RULE_DOMAINS[$i]}"

    # REDUNDANT: already in CLAUDE.md
    if rule_exists_in_file "$text" "$CLAUDE_TARGET"; then
      lines_to_remove+=("$line")
      redundant=$((redundant + 1))
      continue
    fi

    # PROMOTE: 14+ days old, not already in target (only on 7-day cadence)
    if [[ "$timer_elapsed" -eq 1 && "$age" -ge 14 ]]; then
      # Append to CLAUDE.md under ## Auto-Promoted Rules
      if [[ -f "$CLAUDE_TARGET" ]]; then
        if ! grep -q "## Auto-Promoted Rules" "$CLAUDE_TARGET" 2>/dev/null; then
          printf '\n## Auto-Promoted Rules\n\n' >> "$CLAUDE_TARGET"
        fi
        printf '%s [auto-promoted %s]\n' "$line" "$(date +%Y-%m-%d)" >> "$CLAUDE_TARGET"
      fi
      lines_to_remove+=("$line")
      promoted=$((promoted + 1))
      promoted_names+=("${domain}: ${text:0:60}")
      continue
    fi

    # ARCHIVE: 60+ days old and not promoted (only on 7-day cadence)
    if [[ "$timer_elapsed" -eq 1 && "$age" -ge 60 ]]; then
      echo "$line [archived $(date +%Y-%m-%d)]" >> "$ARCHIVE_FILE"
      lines_to_remove+=("$line")
      archived=$((archived + 1))
      archived_names+=("${domain}: ${text:0:40}")
      continue
    fi
  done

  # ─── Remove processed lines from rules.md ────────────────────────
  if [[ ${#lines_to_remove[@]} -gt 0 ]]; then
    local tmp
    tmp=$(mktemp)
    cp "$RULES_FILE" "$tmp"
    for line in "${lines_to_remove[@]}"; do
      # `--` ends option parsing: every rule line starts with "- ", so without it
      # grep reads the leading dash as a flag, errors out (hidden by 2>/dev/null),
      # the old `&&` short-circuited, and NOTHING was ever removed (the root cause
      # of rules.md accumulating already-promoted duplicates). Exit 0 (some lines
      # kept) and 1 (all lines matched → empty output) both apply; only a real
      # grep error (exit 2) skips the swap.
      grep -vF -- "$line" "$tmp" > "${tmp}.new" 2>/dev/null
      if [[ $? -le 1 ]]; then mv "${tmp}.new" "$tmp"; else rm -f "${tmp}.new"; fi
    done
    mv "$tmp" "$RULES_FILE"
  fi

  # ─── Cross-project aggregation ───────────────────────────────────
  local cross_promoted=0
  local CROSS_FILE="$HOME/.claude/corrections/cross-project-rules.jsonl"
  if [[ "$timer_elapsed" -eq 1 ]] && [[ -f "$CROSS_FILE" ]] && command -v jq &>/dev/null; then
    # Find rule_hashes appearing in 2+ DISTINCT projects. Counting raw
    # occurrences let same-project repeats qualify (a prompt pasted twice in
    # one repo promoted verbatim into global CLAUDE.md — the 2026-06 noise).
    local multi_project_hashes
    multi_project_hashes=$(jq -r '"\(.rule_hash)\t\(.project)"' "$CROSS_FILE" 2>/dev/null \
      | sort -u | cut -f1 | uniq -c | sort -rn \
      | awk '$1 >= 2 {print $2}')

    local global_claude="$HOME/.claude/CLAUDE.md"
    for hash in $multi_project_hashes; do
      # Get the rule text for this hash
      local rule_text
      rule_text=$(jq -r --arg h "$hash" 'select(.rule_hash == $h) | .rule_text' "$CROSS_FILE" 2>/dev/null | head -1)
      [[ -z "$rule_text" ]] && continue

      # Markup means pasted HTML or harness-injected <task-notification>,
      # never a promotable rule
      [[ "$rule_text" == \<* ]] && continue

      # Skip if already in global CLAUDE.md
      if rule_exists_in_file "$rule_text" "$global_claude"; then
        continue
      fi

      # Promote to global CLAUDE.md
      if ! grep -q "## Cross-Project Rules" "$global_claude" 2>/dev/null; then
        printf '\n## Cross-Project Rules\n\n' >> "$global_claude"
      fi
      # Format string must NOT start with "-" or bash printf parses it as an
      # option ("invalid option" → nothing written). Keep "%s\n" as the format
      # and build the dash-prefixed line as the argument.
      printf '%s\n' "- $rule_text [cross-project $(date +%Y-%m-%d)]" >> "$global_claude"
      cross_promoted=$((cross_promoted + 1))
    done
  fi

  # ─── Effectiveness warnings ──────────────────────────────────────
  local ineffective_warnings=""
  local ineffective_hashes
  ineffective_hashes=$(get_ineffective_rules 2>/dev/null)
  if [[ -n "$ineffective_hashes" ]]; then
    # Match hashes to current rules
    parse_rules "$RULES_FILE"
    for hash in $ineffective_hashes; do
      for (( i=0; i<${#RULE_TEXTS[@]}; i++ )); do
        local rh
        rh=$(rule_hash "${RULE_TEXTS[$i]}")
        if [[ "$rh" == "$hash" ]]; then
          ineffective_warnings="${ineffective_warnings}  - [INEFFECTIVE] ${RULE_DOMAINS[$i]}: ${RULE_TEXTS[$i]:0:60}\n"
        fi
      done
    done
  fi

  # ─── Hook generation suggestions ────────────────────────────────
  local hook_suggestions=""
  local effective_hashes
  effective_hashes=$(get_effective_rules 2>/dev/null)
  if [[ -n "$effective_hashes" ]]; then
    for hash in $effective_hashes; do
      local data
      data=$(jq -r --arg h "$hash" '.[$h] | "\(.hits)+\(.misses)"' "$EFFECTIVENESS_FILE" 2>/dev/null)
      local hits="${data%%+*}"
      if [[ "${hits:-0}" -ge 3 ]]; then
        hook_suggestions="${hook_suggestions}  - Rule hash $hash has ${hits}+ hits. Run /generate-hook to automate enforcement.\n"
      fi
    done
  fi

  # ─── Touch last-audit ───────────────────────────────────────────
  # Only when the promote/archive pass actually ran — dedup-only sessions must
  # NOT reset the timer, or the 7-day promotion cadence would never elapse.
  [[ "$timer_elapsed" -eq 1 ]] && touch "$LAST_AUDIT_FILE"

  # ─── Build summary ──────────────────────────────────────────────
  local summary=""
  local changes=$((promoted + redundant + archived + cross_promoted))

  if [[ "$changes" -gt 0 ]]; then
    summary="Auto-audit completed: "
    [[ "$promoted" -gt 0 ]] && summary="${summary}${promoted} promoted, "
    [[ "$redundant" -gt 0 ]] && summary="${summary}${redundant} redundant removed, "
    [[ "$archived" -gt 0 ]] && summary="${summary}${archived} archived, "
    [[ "$cross_promoted" -gt 0 ]] && summary="${summary}${cross_promoted} cross-project promoted, "
    summary="${summary%%, }"

    for name in "${promoted_names[@]}"; do
      summary="${summary}\n  → Promoted: ${name}"
    done
  else
    summary="Auto-audit: no changes needed (${total} rules checked)"
  fi

  if [[ -n "$ineffective_warnings" ]]; then
    summary="${summary}\nIneffective rules (miss rate >60%):\n${ineffective_warnings}"
  fi

  if [[ -n "$hook_suggestions" ]]; then
    summary="${summary}\nHook generation candidates:\n${hook_suggestions}"
  fi

  AUDIT_SUMMARY="$summary"
}
