#!/usr/bin/env bash
# rule-injector.sh — PostToolUse hook (matcher: Edit|Write)
#
# Path-scoped rule injection: rules that only matter for certain files live in
# rule files instead of CLAUDE.md, and get injected into context only when the
# agent actually edits a matching file. Keeps base context lean as the
# learned-rule corpus grows.
#
# Sources (project first, then global):
#   $PROJECT/.claude/rules/*.md
#   ~/.claude/rules/*.md
#
# Rule file format (YAML frontmatter + markdown body):
#   ---
#   paths: orchestrator/**/*.py, tests/*.py
#   ---
#   Rule body — injected when an edited file matches one of the globs.
#
# `paths:` accepts a comma-separated line or a YAML list (`- glob` lines).
# Glob semantics (gitignore-style):
#   - pattern containing '/' → matched against the project-relative path
#   - pattern without '/'   → matched against the basename (*.css = any css)
#   - '**' crosses directories; '*' and '?' do not match '/'
# Files without a `paths:` frontmatter key are ignored (not path-scoped).
#
# Dedup: each rule file is injected at most once per session. Sentinel:
#   $PROJECT/.claude/sessions/<session_id>.rules-injected
# (same dir + lifecycle as session-baseline.sh's *.baseline files).
#
# Output: hookSpecificOutput.additionalContext with the matching rule bodies.
# Silent (no output, exit 0) when nothing matches — failure paths included.

set -u

command -v jq &>/dev/null || exit 0

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat 2>/dev/null || true)
fi
[ -z "$INPUT" ] && exit 0

FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
[ -z "$FILE_PATH" ] && exit 0

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Project-relative path (falls back to the absolute path for files outside
# the project — '**/'-prefixed globs still match those).
REL_PATH="$FILE_PATH"
case "$FILE_PATH" in
  "$PROJECT_DIR"/*) REL_PATH="${FILE_PATH#"$PROJECT_DIR"/}" ;;
esac
BASE_NAME="${FILE_PATH##*/}"

SESS_DIR="$PROJECT_DIR/.claude/sessions"
SENT_FILE="$SESS_DIR/${SESSION_ID:-nosession}.rules-injected"

# ─── Glob → ERE conversion ────────────────────────────────────────────
# '**/' → '(.*/)?'   '**' → '.*'   '*' → '[^/]*'   '?' → '[^/]'
# Everything else regex-escaped. Anchored both ends.
glob_to_ere() {
  # NOTE: ${#g} must be expanded in a separate statement — expansions in a
  # `local a=1 b=${#a}` line happen before ANY assignment runs (set -u trap).
  local g="$1" out="" i=0 c n
  n=${#g}
  while [ "$i" -lt "$n" ]; do
    c="${g:i:1}"
    if [ "$c" = "*" ]; then
      if [ "${g:i:3}" = "**/" ]; then out+="(.*/)?"; i=$((i + 3)); continue; fi
      if [ "${g:i:2}" = "**" ]; then out+=".*"; i=$((i + 2)); continue; fi
      out+="[^/]*"
    elif [ "$c" = "?" ]; then
      out+="[^/]"
    else
      case "$c" in
        '.'|'+'|'('|')'|'['|']'|'{'|'}'|'^'|'$'|'|'|'\') out+="\\$c" ;;
        *) out+="$c" ;;
      esac
    fi
    i=$((i + 1))
  done
  printf '%s' "^${out}\$"
}

# ─── Frontmatter parsing ─────────────────────────────────────────────
# Print one glob per line from the `paths:` key (inline comma form or YAML
# list form). Empty output = no frontmatter / no paths key → file ignored.
extract_paths() {
  awk '
    NR == 1 { if ($0 !~ /^---[[:space:]]*$/) exit; next }
    /^---[[:space:]]*$/ { exit }
    /^paths:/ {
      val = $0; sub(/^paths:[[:space:]]*/, "", val)
      if (val != "") { n = split(val, parts, ","); for (j = 1; j <= n; j++) print parts[j] }
      else inlist = 1
      next
    }
    inlist && /^[[:space:]]*-[[:space:]]*/ {
      val = $0; sub(/^[[:space:]]*-[[:space:]]*/, "", val); print val; next
    }
    inlist { inlist = 0 }
  ' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
            -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//" | grep -v '^$' || true
}

# Print the body (everything after the closing '---'). Malformed file with an
# unclosed frontmatter block produces no body → nothing injected.
extract_body() {
  awk '
    NR == 1 { if ($0 ~ /^---[[:space:]]*$/) { infm = 1; next } else exit }
    infm && /^---[[:space:]]*$/ { infm = 0; body = 1; next }
    body { print }
  ' "$1"
}

# ─── Match + collect ─────────────────────────────────────────────────
CONTEXT=""
INJECTED_FILES=""

collect_from_dir() {
  local dir="$1" scope="$2" f pat ere target body matched
  [ -d "$dir" ] || return 0
  for f in "$dir"/*.md; do
    [ -f "$f" ] || continue
    # Once per session per rule file
    grep -qxF "$f" "$SENT_FILE" 2>/dev/null && continue
    matched=""
    while IFS= read -r pat; do
      [ -z "$pat" ] && continue
      target="$REL_PATH"
      case "$pat" in
        */*) : ;;
        *) target="$BASE_NAME" ;;
      esac
      ere=$(glob_to_ere "$pat")
      # Empty ERE would match everything — never inject on a degenerate pattern
      [ -z "$ere" ] && continue
      if [[ "$target" =~ $ere ]]; then matched=1; break; fi
    done < <(extract_paths "$f")
    [ -z "$matched" ] && continue
    body=$(extract_body "$f" | head -c 4000)
    [ -z "$body" ] && continue
    CONTEXT+="[path-scoped rule: $(basename "$f") ($scope) — matched $REL_PATH]
$body

"
    INJECTED_FILES+="$f
"
  done
}

collect_from_dir "$PROJECT_DIR/.claude/rules" "project"
GLOBAL_RULES_DIR="$HOME/.claude/rules"
if [ "$GLOBAL_RULES_DIR" != "$PROJECT_DIR/.claude/rules" ]; then
  collect_from_dir "$GLOBAL_RULES_DIR" "global"
fi

[ -z "$CONTEXT" ] && exit 0

# Record sentinels before emitting (re-running after a failed emit re-injects,
# which is the safe direction).
mkdir -p "$SESS_DIR" 2>/dev/null || true
printf '%s' "$INJECTED_FILES" >> "$SENT_FILE" 2>/dev/null || true
# Cleanup: sentinels older than 7 days (mirrors session-baseline.sh policy)
find "$SESS_DIR" -maxdepth 1 -type f -name '*.rules-injected' -mtime +7 -delete 2>/dev/null || true

jq -n --arg ctx "$CONTEXT" \
  '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":$ctx}}'

exit 0
