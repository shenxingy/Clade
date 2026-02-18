#!/usr/bin/env bash
# correction-detector.sh — Detect user corrections and build a learning history
# Triggered by UserPromptSubmit
# Reads JSON from stdin: {"prompt": "user's message", ...}
# If a correction is detected, logs it and reminds Claude to extract rules.

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')

if [[ -z "$PROMPT" ]]; then
  exit 0
fi

# Correction patterns (Chinese + English)
# Matches: don't/别用/不要/错了/改回/wrong/revert/undo/actually...instead/should have/应该
PATTERNS=(
  '不要|别用|错了|改回|不对|别这样|重新|撤回|应该'
  '\b(wrong|revert|undo|rollback|actually|instead|should have|shouldn'\''t have|go back|put back|change back|not what I)\b'
  '\b(no,? *(use|do|make|try|put))\b'
)

MATCHED=false
for pattern in "${PATTERNS[@]}"; do
  if echo "$PROMPT" | grep -qiP "$pattern" 2>/dev/null || echo "$PROMPT" | grep -qiE "$pattern" 2>/dev/null; then
    MATCHED=true
    break
  fi
done

if ! $MATCHED; then
  exit 0
fi

# Log to correction history
CORRECTIONS_DIR="$HOME/.claude/corrections"
mkdir -p "$CORRECTIONS_DIR"

HISTORY_FILE="$CORRECTIONS_DIR/history.jsonl"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PROJECT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

jq -n \
  --arg ts "$TIMESTAMP" \
  --arg prompt "$PROMPT" \
  --arg project "$PROJECT" \
  '{timestamp: $ts, prompt: $prompt, project: $project}' >> "$HISTORY_FILE"

# Remind Claude to extract a rule
CONTEXT="A user correction was detected in the prompt above. After addressing the user's request:
1. Extract the lesson (what was wrong, what's correct)
2. Append a concise rule to ~/.claude/corrections/rules.md in this format:
   - [YYYY-MM-DD] <domain>: <do this> instead of <not this>
   Example: - [2026-02-17] imports: Use @/ path aliases instead of relative paths
3. Keep rules.md under 30 lines — remove outdated rules if needed"

jq -n --arg ctx "$CONTEXT" \
  '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'

exit 0
