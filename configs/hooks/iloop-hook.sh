#!/usr/bin/env bash
# iloop-hook.sh — Stop hook: in-session iterative loop
#
# When .claude/iloop.local.md exists with active:true, prevents session exit
# and feeds the task prompt back to continue the loop.
#
# Supports:
#   <loop-abort>reason</loop-abort>  — terminate loop immediately
#   <loop-pause>what needed</loop-pause>  — pause loop, keep state
#   <promise>TEXT</promise>  — signal completion (when TEXT matches completion_promise)
#
# Adapted from pua (MIT) — https://github.com/tanweai/pua

set -euo pipefail
command -v jq &>/dev/null || exit 0

HOOK_INPUT=$(cat)
STATE_FILE=".claude/iloop.local.md"

# No active loop — allow exit
[[ ! -f "$STATE_FILE" ]] && exit 0

# Normalize CRLF → LF (Windows/WSL compat)
TEMP_NORM="${STATE_FILE}.norm.$$"
tr -d '\r' < "$STATE_FILE" > "$TEMP_NORM" && mv "$TEMP_NORM" "$STATE_FILE"

# ─── Parse frontmatter ────────────────────────────────────────────────────────

FRONTMATTER=$(sed -n '/^---$/,/^---$/{ /^---$/d; p; }' "$STATE_FILE" | tr -d '\r')

_field() { echo "$FRONTMATTER" | grep "^${1}:" | sed "s/${1}: *//" || true; }

LOOP_ACTIVE=$(_field active)
ITERATION=$(_field iteration)
MAX_ITERATIONS=$(_field max_iterations)
COMPLETION_PROMISE=$(_field completion_promise | sed "s/^\"//; s/\"$//" || true)
STATE_SESSION=$(_field session_id)

# Paused loop — allow exit
[[ "$LOOP_ACTIVE" == "false" ]] && exit 0

# ─── Session isolation ────────────────────────────────────────────────────────

HOOK_SESSION=$(echo "$HOOK_INPUT" | jq -r '.session_id // ""')

# Auto-bind: if state has no session_id yet, bind this session
if [[ -z "$STATE_SESSION" ]] && [[ -n "$HOOK_SESSION" ]]; then
  TEMP_FILE="${STATE_FILE}.tmp.$$"
  sed "s/^session_id:.*/session_id: $HOOK_SESSION/" "$STATE_FILE" > "$TEMP_FILE"
  mv "$TEMP_FILE" "$STATE_FILE"
  STATE_SESSION="$HOOK_SESSION"
fi

# Different session started this loop — don't interfere
if [[ -n "$STATE_SESSION" ]] && [[ "$STATE_SESSION" != "$HOOK_SESSION" ]]; then
  exit 0
fi

# ─── Validate numeric fields ──────────────────────────────────────────────────

if [[ ! "$ITERATION" =~ ^[0-9]+$ ]]; then
  echo "⚠ iloop: State file corrupted (iteration='$ITERATION'). Stopping." >&2
  rm -f "$STATE_FILE"
  exit 0
fi

if [[ ! "$MAX_ITERATIONS" =~ ^[0-9]+$ ]]; then
  echo "⚠ iloop: State file corrupted (max_iterations='$MAX_ITERATIONS'). Stopping." >&2
  rm -f "$STATE_FILE"
  exit 0
fi

# Max iterations reached
if [[ $MAX_ITERATIONS -gt 0 ]] && [[ $ITERATION -ge $MAX_ITERATIONS ]]; then
  echo "🛑 iloop: Max iterations ($MAX_ITERATIONS) reached."
  rm -f "$STATE_FILE"
  exit 0
fi

# ─── Read last assistant output from transcript ───────────────────────────────

TRANSCRIPT_PATH=$(echo "$HOOK_INPUT" | jq -r '.transcript_path // ""')

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
  echo "⚠ iloop: Transcript not found ($TRANSCRIPT_PATH). Stopping." >&2
  rm -f "$STATE_FILE"
  exit 0
fi

if ! grep -q '"role":"assistant"' "$TRANSCRIPT_PATH" 2>/dev/null; then
  echo "⚠ iloop: No assistant messages in transcript. Stopping." >&2
  rm -f "$STATE_FILE"
  exit 0
fi

# Extract the last assistant text block
set +e
LAST_OUTPUT=$(grep '"role":"assistant"' "$TRANSCRIPT_PATH" | tail -n 100 | \
  jq -rs 'map(.message.content[]? | select(.type == "text") | .text) | last // ""' 2>&1)
JQ_EXIT=$?
set -e

if [[ $JQ_EXIT -ne 0 ]]; then
  echo "⚠ iloop: Failed to parse transcript JSON. Stopping." >&2
  rm -f "$STATE_FILE"
  exit 0
fi

# ─── Check exit signals (priority: abort > pause > promise) ──────────────────

# <loop-abort>reason</loop-abort> — terminate completely
ABORT_TEXT=$(echo "$LAST_OUTPUT" | \
  perl -0777 -ne 'if (/<loop-abort>(.*?)<\/loop-abort>/s){$t=$1;$t=~s/^\s+|\s+$//g;print $t}' 2>/dev/null || true)
if [[ -n "$ABORT_TEXT" ]]; then
  echo "🛑 iloop: Loop aborted. Reason: $ABORT_TEXT"
  rm -f "$STATE_FILE"
  exit 0
fi

# <loop-pause>what needed</loop-pause> — pause for manual intervention
PAUSE_TEXT=$(echo "$LAST_OUTPUT" | \
  perl -0777 -ne 'if (/<loop-pause>(.*?)<\/loop-pause>/s){$t=$1;$t=~s/^\s+|\s+$//g;print $t}' 2>/dev/null || true)
if [[ -n "$PAUSE_TEXT" ]]; then
  TEMP_FILE="${STATE_FILE}.tmp.$$"
  sed "s/^active:.*/active: false/" "$STATE_FILE" | \
    sed "s/^session_id:.*/session_id: /" > "$TEMP_FILE"
  mv "$TEMP_FILE" "$STATE_FILE"
  printf '\n⏸  iloop paused (iteration %s)\n   Manual action needed: %s\n   State saved in %s — reopen session to resume.\n\n' \
    "$ITERATION" "$PAUSE_TEXT" "$STATE_FILE"
  exit 0
fi

# <promise>TEXT</promise> — completion signal (only when text matches)
if [[ -n "$COMPLETION_PROMISE" && "$COMPLETION_PROMISE" != "null" ]]; then
  PROMISE_TEXT=$(echo "$LAST_OUTPUT" | \
    perl -0777 -pe 's/.*?<promise>(.*?)<\/promise>.*/$1/s; s/^\s+|\s+$//g; s/\s+/ /g' 2>/dev/null || true)
  if [[ -n "$PROMISE_TEXT" ]] && [[ "$PROMISE_TEXT" = "$COMPLETION_PROMISE" ]]; then
    echo "✅ iloop: Completion promise matched. Loop done."
    rm -f "$STATE_FILE"
    exit 0
  fi
fi

# ─── Continue loop ────────────────────────────────────────────────────────────

NEXT_ITERATION=$((ITERATION + 1))

# Extract prompt body (everything after closing ---)
PROMPT_TEXT=$(awk '/^---$/{i++; next} i>=2' "$STATE_FILE")

if [[ -z "$PROMPT_TEXT" ]]; then
  echo "⚠ iloop: No prompt body in state file. Stopping." >&2
  rm -f "$STATE_FILE"
  exit 0
fi

# Update iteration counter
TEMP_FILE="${STATE_FILE}.tmp.$$"
sed "s/^iteration: .*/iteration: $NEXT_ITERATION/" "$STATE_FILE" > "$TEMP_FILE"
mv "$TEMP_FILE" "$STATE_FILE"

# Build iteration message
if [[ $NEXT_ITERATION -le 3 ]]; then
  ITER_MSG="Iteration $NEXT_ITERATION — continuing."
elif [[ $NEXT_ITERATION -le 7 ]]; then
  ITER_MSG="Iteration $NEXT_ITERATION — switch approach if still stuck, don't spin."
elif [[ $NEXT_ITERATION -le 15 ]]; then
  ITER_MSG="Iteration $NEXT_ITERATION — what is the root cause? Are you repeating the same mistake?"
else
  ITER_MSG="Iteration $NEXT_ITERATION — final stretch. Exhaust everything or abort with <loop-abort>."
fi

if [[ -n "$COMPLETION_PROMISE" && "$COMPLETION_PROMISE" != "null" ]]; then
  SYSTEM_MSG="$ITER_MSG | Output <promise>$COMPLETION_PROMISE</promise> ONLY when genuinely complete | Abort: <loop-abort>reason</loop-abort> | Pause: <loop-pause>what needed</loop-pause>"
else
  SYSTEM_MSG="$ITER_MSG | Abort: <loop-abort>reason</loop-abort> | Pause: <loop-pause>what needed</loop-pause>"
fi

jq -n \
  --arg prompt "$PROMPT_TEXT" \
  --arg msg "$SYSTEM_MSG" \
  '{
    "decision": "block",
    "reason": $prompt,
    "systemMessage": $msg
  }'

exit 0
