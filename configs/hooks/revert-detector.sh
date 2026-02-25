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

# ─── Log as implicit correction ──────────────────────────────────────
CORRECTIONS_DIR="$HOME/.claude/corrections"
mkdir -p "$CORRECTIONS_DIR" 2>/dev/null
HISTORY_FILE="$CORRECTIONS_DIR/history.jsonl"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PROJECT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

jq -n \
  --arg ts "$TIMESTAMP" \
  --arg prompt "$COMMAND" \
  --arg project "$PROJECT" \
  --arg type "implicit-revert" \
  '{timestamp: $ts, prompt: $prompt, project: $project, type: $type}' >> "$HISTORY_FILE" 2>/dev/null

exit 0
