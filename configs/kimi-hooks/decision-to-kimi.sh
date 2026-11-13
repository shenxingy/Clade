#!/usr/bin/env bash
# decision-to-kimi.sh — run a Claude-Code-style hook unmodified under Kimi Code.
# exists-for: Kimi silently allowed Claude deny JSON before the guardian bridge (fixed 2026-09-18 in ca51556) · retire-when: Kimi natively accepts every Claude hook input/output shape used here and provides an equivalent first-prompt context channel
#
# Kimi 2.6.0 protocol evidence (bundled agent-core-v2 source):
# - internal/matchHooks.ts:toHookInputData supplies snake_case fields, including
#   hook_event_name; UserPromptSubmit.prompt is an array of content parts.
# - agent/tools/edit/edit.ts and agent/tools/os/write/write.ts name the path
#   argument `path`, while the Claude hooks wrapped here read `file_path`.
# - internal/runHook.ts:resultFromExitCode blocks on exit 2 or on
#   hookSpecificOutput.permissionDecision="deny". Other non-zero exits allow.
# - internal/userPrompt.ts injects a non-blocking `message`, or plain stdout,
#   only for UserPromptSubmit. PreToolUse/Stop consume only a block reason;
#   PostToolUse is fire-and-forget and SessionStart discards hook results.
#
# Usage:
#   decision-to-kimi.sh [--once-per-session] /path/to/claude-style-hook.sh
#
# --once-per-session is for SessionStart context hooks wired instead to the
# first UserPromptSubmit. An atomic runtime-dir sentinel delivers once per Kimi
# session_id. All adapter failures fail open: no output, exit 0.

set -uo pipefail

ONCE_PER_SESSION=0
if [[ "${1:-}" == "--once-per-session" ]]; then
  ONCE_PER_SESSION=1
  shift
fi

WRAPPED="${1:-}"
if [[ -z "$WRAPPED" || ! -x "$WRAPPED" ]]; then
  exit 0
fi
command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
NORMALIZED=$(printf '%s' "$INPUT" | jq -c '
  (if (.prompt? | type) == "array" then
     .prompt = ([.prompt[]
                 | select((.type? == "text") and ((.text? | type) == "string"))
                 | .text]
                | join("\n"))
   else . end)
  | (if ((.tool_name? == "Edit") or (.tool_name? == "Write"))
         and ((.tool_input? | type) == "object")
         and ((.tool_input.file_path? | type) != "string")
         and ((.tool_input.path? | type) == "string")
     then .tool_input.file_path = .tool_input.path
     else . end)
  | .hook_event_name = (.hook_event_name // .hookEventName // "")
  | .transcript_path = (.transcript_path // null)
' 2>/dev/null || true)
if [[ -z "$NORMALIZED" ]]; then
  NORMALIZED="$INPUT"
fi
EVENT=$(printf '%s' "$NORMALIZED" | jq -r '.hook_event_name // empty' 2>/dev/null || true)

if [[ "$ONCE_PER_SESSION" == 1 ]]; then
  [[ "$EVENT" == "UserPromptSubmit" ]] || exit 0
  SESSION_ID=$(printf '%s' "$NORMALIZED" | jq -r '.session_id // empty' 2>/dev/null || true)
  [[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0
  RUNTIME_LIB="$(dirname "$WRAPPED")/lib/runtime-dir.sh"
  # shellcheck source=/dev/null
  source "$RUNTIME_LIB" 2>/dev/null || exit 0
  STATE_DIR=$(clade_state_dir kimi-session-context 2>/dev/null) || exit 0
  SENTINEL="$STATE_DIR/$SESSION_ID.$(basename "$WRAPPED").once"
  mkdir "$SENTINEL" 2>/dev/null || exit 0
fi

ERR_FILE=$(mktemp 2>/dev/null) || exit 0
trap 'rm -f "$ERR_FILE" 2>/dev/null || true' EXIT
OUTPUT=$(printf '%s' "$NORMALIZED" | "$WRAPPED" 2>"$ERR_FILE")
WRAPPED_RC=$?

if [[ "$WRAPPED_RC" == 2 ]]; then
  REASON=$(cat "$ERR_FILE" 2>/dev/null || true)
  [[ -n "$REASON" ]] || REASON="Blocked by ${EVENT:-hook} hook"
  jq -n --arg reason "$REASON" \
    '{hookSpecificOutput:{permissionDecision:"deny",permissionDecisionReason:$reason}}'
  exit 0
fi
# Kimi fails open on every other non-zero exit; do not inject partial output.
[[ "$WRAPPED_RC" == 0 ]] || exit 0

VERDICT=$(printf '%s' "$OUTPUT" | jq -c '
  . as $root
  | (.hookSpecificOutput // {}) as $h
  | ($h.updatedInput? // .updatedInput?) as $rewrite
  | if .decision? == "block" then
      {kind:"block", text:(.reason // "")}
    elif $h.permissionDecision? == "deny" then
      {kind:"block", text:($h.permissionDecisionReason // "")}
    elif ($rewrite | type) == "object" then
      {kind:"block", text:(
        (if ($rewrite.command? | type) == "string" then
           "Refused as written. Run this safer form instead: " + $rewrite.command
         else
           "Refused as written. The hook requested revised tool input, which Kimi cannot apply: "
             + ($rewrite | tojson)
         end)
        + (if (($h.additionalContext? | type) == "string" and ($h.additionalContext | length) > 0)
           then " — " + $h.additionalContext else "" end))}
    elif (($h.additionalContext? // .additionalContext? | type) == "string")
         and (($h.additionalContext? // .additionalContext? | length) > 0) then
      {kind:"context", text:($h.additionalContext? // .additionalContext?)}
    else empty
    end
' 2>/dev/null || true)

if [[ -n "$VERDICT" ]]; then
  KIND=$(printf '%s' "$VERDICT" | jq -r '.kind // empty' 2>/dev/null || true)
  TEXT=$(printf '%s' "$VERDICT" | jq -r '.text // empty' 2>/dev/null || true)
  if [[ "$KIND" == "block" ]]; then
    [[ -n "$TEXT" ]] || TEXT="Blocked by ${EVENT:-hook} hook"
    jq -n --arg reason "$TEXT" \
      '{hookSpecificOutput:{permissionDecision:"deny",permissionDecisionReason:$reason}}'
  elif [[ "$KIND" == "context" && "$EVENT" == "UserPromptSubmit" && -n "$TEXT" ]]; then
    jq -n --arg message "$TEXT" '{message:$message}'
  fi
elif [[ "$EVENT" == "UserPromptSubmit" && -n "$OUTPUT" ]]; then
  # Kimi's own plain-stdout context channel; structured JSON without a message
  # parses as structured output and therefore remains silent.
  printf '%s\n' "$OUTPUT"
fi
exit 0
