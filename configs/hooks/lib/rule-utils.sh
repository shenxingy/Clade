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
  # `grep -c` prints "0" and exits 1 on no match; `|| echo 0` inside the
  # substitution would make it "0\n0".
  RULE_COUNT=$(grep -c '^- \[' "$file" 2>/dev/null) || RULE_COUNT=0
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
#
# `standing-preference` was added for the same reason one level up: it is the
# only class whose evidence is a COUNT rather than an incident, and there was
# nowhere to file it. Measured on this machine's own log at the time: 386,760
# prompts, 2,990 distinct fingerprints, nine of them past the repeat threshold,
# and one 9,181-character design brief hand-typed fifteen times across five
# months at a skill that did not contain a single one of its constraints. Every
# instance was answered correctly, so no correction was ever recorded and the
# taxonomy never saw it. Promotable because persisting into every session is
# not a side effect of the class — it is the entire remedy.
RULE_PROMOTABLE_ROOT_CAUSES="security async-race deploy-gap settings-disconnect data-loss inaccurate-self-reporting constraint-violation standing-preference"

rule_earns_promotion() {
  case "${1:-}" in
    security|async-race|deploy-gap|settings-disconnect|data-loss) return 0 ;;
    inaccurate-self-reporting|constraint-violation) return 0 ;;
    standing-preference) return 0 ;;
    *) return 1 ;;
  esac
}

# ─── claude_md_budget / promotion_fits ───────────────────────────────
# Claude Code loads every instruction file whole — into every session AND every
# subagent — and only WARNS past its limits. Per file the limit is
# max(40000, context window × 0.05 × chars-per-token); in total it is
# max(120000, that). On a 200k-context model that is 40,000 per file and
# 120,000 in total; on a 1M model, 150,000 for both (Claude Code 2.1.283,
# read from the binary 2026-10-18). Nothing here checked either limit, so
# promotion grew one project's CLAUDE.md to 127,095 chars (158 rules, 82 of
# them already archived verbatim elsewhere) and the global one to 73,577; one
# session there loaded 237k chars against a 150k limit.
#
# The budget is the SMALLEST per-file limit Claude Code applies, so a target
# that fits it fits every model. Bytes rather than characters: `wc -c` is the
# same on GNU and BSD, and it over-counts CJK, so the gate trips early, never
# late. CLADE_CLAUDE_MD_BUDGET overrides it.
claude_md_budget() {
  local b="${CLADE_CLAUDE_MD_BUDGET:-40000}"
  [[ "$b" =~ ^[0-9]+$ ]] || b=40000
  echo "$b"
}

# Would appending ENTRY keep TARGET within the budget? The +2 covers the
# newline and a possible blank line before a newly created section heading.
promotion_fits() {
  local target="${1:-}" entry="${2:-}"
  local size budget
  size=$(wc -c < "$target" 2>/dev/null | tr -d ' ') || size=0
  budget=$(claude_md_budget)
  (( ${size:-0} + ${#entry} + 2 <= budget ))
}

# ─── append_to_section ───────────────────────────────────────────────
# Insert LINE as the last entry of the section whose heading line starts with
# HEADING, or create the section at end of file when there is none.
#
# Appending at end of file assumed the section was the file's last. Once a later
# section existed — the global file's "## Internal Machine Map" — 27 promoted
# rules landed inside it, where neither a reader nor `/audit` looked for them.
# The section ends at the next "# " or "## " heading; deeper headings belong to
# it. Values go through ENVIRON, not `awk -v`, which would expand the
# backslashes rule text carries. The file is rewritten in place (cat >), not
# replaced (mv), so a symlinked CLAUDE.md stays a symlink.
append_to_section() {
  local file="${1:-}" heading="${2:-}" line="${3:-}"
  [[ -f "$file" ]] || return 1
  local tmp
  tmp=$(mktemp) || return 1
  if HEADING="$heading" LINE="$line" awk '
      { buf[NR] = $0 }
      END {
        h = ENVIRON["HEADING"]; start = 0; last = 0; ended = 0
        for (i = 1; i <= NR; i++) {
          if (!start) {
            if (index(buf[i], h) == 1) { start = i; last = i }
            continue
          }
          if (ended) continue
          if (substr(buf[i], 1, 2) == "# " || substr(buf[i], 1, 3) == "## ") { ended = 1; continue }
          if (buf[i] !~ /^[ \t]*$/) last = i
        }
        for (i = 1; i <= NR; i++) {
          print buf[i]
          if (start && i == last) {
            if (last == start) print ""
            print ENVIRON["LINE"]
          }
        }
        if (!start) { print ""; print h; print ""; print ENVIRON["LINE"] }
      }' "$file" > "$tmp"; then
    cat "$tmp" > "$file"
  fi
  rm -f "$tmp"
}
