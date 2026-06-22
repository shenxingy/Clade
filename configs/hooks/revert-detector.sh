#!/usr/bin/env bash
# revert-detector.sh — Detect git revert/reset commands as implicit corrections
# Triggered by PreToolUse on Bash
#
# When a user (or Claude) runs git revert, git reset --hard, git checkout -- <file>,
# or git restore <file>, log it as an implicit correction signal.
#
# Fail-open: errors are silently ignored. Does NOT block the command.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")

if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")

if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# ─── Detect revert patterns ──────────────────────────────────────────
REVERT_PATTERNS=(
  'git[[:space:]]+revert'
  'git[[:space:]]+reset[[:space:]]+--hard'
  'git[[:space:]]+checkout[[:space:]]+--[[:space:]]'
  'git[[:space:]]+restore[[:space:]]'
)

MATCHED=false
for pattern in "${REVERT_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$pattern" 2>/dev/null; then
    MATCHED=true
    break
  fi
done

if ! $MATCHED; then
  exit 0
fi

# ─── Log as implicit correction, paired with the rejected files ───────
LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/correction-pair.sh" 2>/dev/null || true

CORRECTIONS_DIR="$HOME/.claude/corrections"
mkdir -p "$CORRECTIONS_DIR" 2>/dev/null
HISTORY_FILE="$CORRECTIONS_DIR/history.jsonl"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PROJECT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Cross-reference the edit-shadow log: which files did Claude recently write that
# this revert is throwing away? This is the "AI did X → rejected" half of the pair
# (and consumes the shadow data that was previously written but never read).
REVERTED_FILES_JSON='[]'
if declare -f cp_recent_files >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  _files=$(cp_recent_files "$(cp_session_key "$INPUT")" 20)
  if [[ -n "$_files" ]]; then
    REVERTED_FILES_JSON=$(printf '%s\n' "$_files" | jq -R . | jq -s 'map(select(length>0))' 2>/dev/null || echo '[]')
  fi
fi

# repeat = has any of these files already been reverted before in this project?
# (a repeated revert is a stronger signal than a one-off — surfaced as data for
# auto-audit / humans; it does NOT auto-write a rule.)
REPEAT=false
if [[ "$REVERTED_FILES_JSON" != "[]" ]] && [[ -f "$HISTORY_FILE" ]] && command -v jq >/dev/null 2>&1; then
  if tail -n 500 "$HISTORY_FILE" 2>/dev/null | jq -es \
       --argjson now "$REVERTED_FILES_JSON" --arg proj "$PROJECT" '
         [ .[] | select(.type=="implicit-revert" and .project==$proj)
               | (.reverted_files // [])[] ] as $past
         | any($past[]; ($now | index(.)) != null)
       ' >/dev/null 2>&1; then
    REPEAT=true
  fi
fi

jq -nc \
  --arg ts "$TIMESTAMP" \
  --arg prompt "$COMMAND" \
  --arg project "$PROJECT" \
  --arg type "implicit-revert" \
  --argjson files "$REVERTED_FILES_JSON" \
  --argjson repeat "$REPEAT" \
  '{timestamp:$ts, prompt:$prompt, project:$project, type:$type, reverted_files:$files, repeat:$repeat}' \
  >> "$HISTORY_FILE" 2>/dev/null

exit 0
