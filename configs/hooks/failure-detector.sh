#!/usr/bin/env bash
# failure-detector.sh — PostToolUse hook: track consecutive Bash failures → inject debugging pressure
#
# Counts consecutive Bash command failures per session. When a command fails 2+ times
# in a row, injects escalating debugging guidance to break spinning patterns.
#
# Adapted from pua (MIT) — https://github.com/tanweai/pua

set -euo pipefail
command -v jq &>/dev/null || exit 0

HOOK_INPUT=$(cat)

# Only process Bash tool results
TOOL_NAME=$(echo "$HOOK_INPUT" | jq -r '.tool_name // ""' 2>/dev/null || true)
[[ "$TOOL_NAME" != "Bash" ]] && exit 0

COUNTER_FILE="${HOME}/.claude/.failure_count"
SESSION_FILE="${HOME}/.claude/.failure_session"

# ─── Parse failure signals ────────────────────────────────────────────────────

IS_ERROR=false

# Check exit_code from tool_result
EXIT_CODE=$(echo "$HOOK_INPUT" | jq -r '
  .tool_result |
  if type == "object" then
    .exit_code // .exitCode // 0
  else 0 end
' 2>/dev/null || echo "0")

if [[ "$EXIT_CODE" != "0" && "$EXIT_CODE" != "" && "$EXIT_CODE" != "null" ]]; then
  IS_ERROR=true
fi

# Check for error patterns in output text
TOOL_TEXT=$(echo "$HOOK_INPUT" | jq -r '
  .tool_result |
  if type == "object" then
    [.content[]? | select(.type == "text") | .text] | join("\n")
  elif type == "string" then .
  else "" end
' 2>/dev/null | head -c 3000 || true)

if echo "$TOOL_TEXT" | grep -qiE \
  'Error:|ERROR:|error:|Traceback|Exception:|FAILED|fatal:|command not found|No such file|Permission denied|exit code [1-9]' \
  2>/dev/null; then
  IS_ERROR=true
fi

# ─── Session-scoped counter ───────────────────────────────────────────────────

CURRENT_SESSION=$(echo "$HOOK_INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
STORED_SESSION=""
[[ -f "$SESSION_FILE" ]] && STORED_SESSION=$(cat "$SESSION_FILE" 2>/dev/null || true)

if [[ "$CURRENT_SESSION" != "$STORED_SESSION" ]]; then
  echo "0" > "$COUNTER_FILE"
  echo "$CURRENT_SESSION" > "$SESSION_FILE"
fi

COUNT=0
[[ -f "$COUNTER_FILE" ]] && COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo "0")
[[ -z "$COUNT" || ! "$COUNT" =~ ^[0-9]+$ ]] && COUNT=0

if [[ "$IS_ERROR" == "true" ]]; then
  COUNT=$((COUNT + 1))
  echo "$COUNT" > "$COUNTER_FILE"
else
  # Success resets consecutive failure counter
  [[ "$COUNT" -gt 0 ]] && echo "0" > "$COUNTER_FILE"
  exit 0
fi

# Only intervene after 2+ consecutive failures
[[ "$COUNT" -lt 2 ]] && exit 0

# ─── Escalating guidance ──────────────────────────────────────────────────────

if [[ "$COUNT" -eq 2 ]]; then
  MSG="[Failure Detector — 2 consecutive failures]

You MUST switch to a FUNDAMENTALLY different approach. Not parameter tweaking — a different strategy.
Ask yourself before retrying:
- What assumption have I NOT verified yet?
- Have I searched for the actual error message (WebSearch / Grep)?
- Am I reading the right file / checking the right path?
- What would the opposite approach look like?"

elif [[ "$COUNT" -eq 3 ]]; then
  MSG="[Failure Detector — 3 consecutive failures — Systematic Checklist Required]

You MUST complete ALL these steps before trying again:
1. Read the error message word by word — what does it ACTUALLY say?
2. Search for the core problem (WebSearch / Grep) — do not guess
3. Read the original context around the failure (50 lines up/down)
4. List 3 fundamentally different hypotheses about the root cause
5. Verify your main assumption is correct — then try reversing it

Do NOT retry the same approach with minor changes."

else
  MSG="[Failure Detector — ${COUNT} consecutive failures — Exhaustion Protocol]

Current approach has FAILED ${COUNT} times. Mandatory escalation:
1. Question the requirement: does this step even need to exist?
2. Attack your own solution: what if your CORE ASSUMPTION is wrong?
3. Go to the lowest level: read source code line by line, read raw error output
4. Cut all middle layers: what is the SHORTEST path from problem to solution?

If all reasonable approaches are exhausted → produce a structured failure report:
  - Verified facts
  - Excluded possibilities (with evidence for each exclusion)
  - Narrowed problem scope
  - Recommended next steps for the user"
fi

jq -n --arg ctx "$MSG" \
  '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":$ctx}}'

exit 0
