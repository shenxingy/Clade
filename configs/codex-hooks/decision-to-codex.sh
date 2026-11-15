#!/usr/bin/env bash
# decision-to-codex.sh — run an unmodified Claude Code command hook under Codex.
# exists-for: Codex 0.169.0 gained Claude-compatible hooks but apply_patch and deny output need translation (ported 2026-11-14) · retire-when: Codex natively supplies per-file Edit/Write payloads and accepts every Claude output shape used by the ported hooks
#
# Codex evidence: rust-v0.169.0:codex-rs/core/src/tools/handlers/apply_patch.rs:370
# sends tool_name=apply_patch and tool_input.command=<raw patch>. Its Write/Edit
# matcher aliases do NOT change that stdin name (core/src/tools/hook_names.rs:27).
# rust-v0.169.0:codex-rs/hooks/src/engine/output_parser.rs:441-470 accepts a
# PreToolUse deny only with a non-empty permissionDecisionReason. schema.rs:245
# requires hookSpecificOutput.hookEventName and rejects unknown fields.
#
# Add File becomes Write with content. Update File becomes Edit with removed and
# added lines in old_string/new_string. Delete File becomes Edit with empty
# old_string and new_string: the patch grammar gives a delete no body
# (codex-rs/apply-patch/src/parser.rs:13), so only its path reaches the hook.
# Move emits two Edit calls (source
# and destination); both carry old_file_path and new_file_path so neither side of
# a rename can bypass a path guard. Every path is absolute against payload.cwd.
#
# All adapter failures fail open: no output, exit 0. A wrapped deny is translated
# to the exact event-specific JSON Codex parses and still exits 0.

set -uo pipefail

WRAPPED="${1:-}"
if [[ -z "$WRAPPED" || ! -x "$WRAPPED" ]]; then
  exit 0
fi
command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
NORMALIZED=$(printf '%s' "$INPUT" | jq -c '
  if type != "object" then error("hook input is not an object")
  else .hook_event_name = (.hook_event_name // .hookEventName // "")
       | .transcript_path = (.transcript_path // null)
  end
' 2>/dev/null)
[[ -n "$NORMALIZED" ]] || exit 0
EVENT=$(printf '%s' "$NORMALIZED" | jq -r '.hook_event_name // empty' 2>/dev/null) || exit 0
PROJECT_DIR=$(printf '%s' "$NORMALIZED" | jq -r 'if (.cwd | type) == "string" then .cwd else "" end' 2>/dev/null) || exit 0
[[ -n "$PROJECT_DIR" ]] || PROJECT_DIR=$(pwd)

ERR_FILE=$(mktemp 2>/dev/null) || exit 0
trap 'rm -f "$ERR_FILE" 2>/dev/null || true' EXIT
RUN_OUTPUT=""
RUN_RC=0
RUN_ERROR=""

run_wrapped() {
  RUN_OUTPUT=$(printf '%s' "$1" | CLAUDE_PROJECT_DIR="$PROJECT_DIR" "$WRAPPED" 2>"$ERR_FILE")
  RUN_RC=$?
  RUN_ERROR=$(cat "$ERR_FILE" 2>/dev/null || true)
}

emit_block() {
  local reason="$1"
  [[ -n "${reason//[[:space:]]/}" ]] || reason="Blocked by ${EVENT:-hook} hook"
  case "$EVENT" in
    PreToolUse)
      jq -n --arg reason "$reason" \
        '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
      ;;
    UserPromptSubmit|PostToolUse|Stop|SubagentStop)
      jq -n --arg reason "$reason" '{decision:"block",reason:$reason}'
      ;;
  esac
}

# translate_result <fanout> — set TRANSLATED to one safe Codex JSON object.
translate_result() {
  local fanout="$1"
  TRANSLATED=""
  if [[ "$RUN_RC" == 2 ]]; then
    TRANSLATED=$(emit_block "$RUN_ERROR")
    return 0
  fi
  [[ "$RUN_RC" == 0 && -n "${RUN_OUTPUT//[[:space:]]/}" ]] || return 0

  local verdict
  verdict=$(printf '%s' "$RUN_OUTPUT" | jq -c '
    . as $root
    | (if ($root.hookSpecificOutput? | type) == "object" then $root.hookSpecificOutput else {} end) as $h
    | ($h.updatedInput? // $root.updatedInput?) as $rewrite
    | {
        block: (($root.decision? == "block") or ($h.permissionDecision? == "deny") or ($h.permissionDecision? == "ask")),
        reason: ($h.permissionDecisionReason? // $root.reason? // ""),
        rewrite: (if ($rewrite | type) == "object" then $rewrite else null end),
        context: (if (($h.additionalContext? // $root.additionalContext?) | type) == "string"
                  then ($h.additionalContext? // $root.additionalContext?) else "" end),
        system: (if ($root.systemMessage? | type) == "string" then $root.systemMessage else "" end)
      }
  ' 2>/dev/null) || return 0

  if [[ $(printf '%s' "$verdict" | jq -r '.block') == true ]]; then
    local reason
    reason=$(printf '%s' "$verdict" | jq -r '.reason // ""')
    TRANSLATED=$(emit_block "$reason")
    return 0
  fi

  local rewrite
  rewrite=$(printf '%s' "$verdict" | jq -c '.rewrite // empty')
  if [[ -n "$rewrite" ]]; then
    if [[ "$EVENT" == PreToolUse && "$fanout" == 0 ]]; then
      TRANSLATED=$(jq -n --argjson input "$rewrite" \
        '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"allow",updatedInput:$input}}')
    elif [[ "$EVENT" == PreToolUse ]]; then
      TRANSLATED=$(emit_block "The hook requested a per-file input rewrite; Codex cannot safely recombine a multi-file apply_patch rewrite")
    fi
    return 0
  fi

  local context system
  context=$(printf '%s' "$verdict" | jq -r '.context // empty')
  system=$(printf '%s' "$verdict" | jq -r '.system // empty')
  if [[ -n "$context" ]]; then
    case "$EVENT" in
      SessionStart|SubagentStart|UserPromptSubmit|PreToolUse|PostToolUse)
        TRANSLATED=$(jq -n --arg event "$EVENT" --arg context "$context" --arg system "$system" \
          '({} + if $system != "" then {systemMessage:$system} else {} end)
           + {hookSpecificOutput:{hookEventName:$event,additionalContext:$context}}')
        ;;
    esac
  elif [[ -n "$system" ]]; then
    TRANSLATED=$(jq -n --arg system "$system" '{systemMessage:$system}')
  fi
}

is_block_output() {
  printf '%s' "$1" | jq -e '
    .decision? == "block" or .hookSpecificOutput.permissionDecision? == "deny"
  ' >/dev/null 2>&1
}

TOOL_NAME=$(printf '%s' "$NORMALIZED" | jq -r '.tool_name // empty' 2>/dev/null) || exit 0
if [[ "$TOOL_NAME" == apply_patch && ( "$EVENT" == PreToolUse || "$EVENT" == PostToolUse ) ]] \
   && printf '%s' "$NORMALIZED" | jq -e '(.tool_input.command | type) == "string"' >/dev/null 2>&1; then
  PATCH_PAYLOADS=$(printf '%s' "$NORMALIZED" | jq -c '
    def absolute($cwd):
      if startswith("/") then .
      elif ($cwd | type) == "string" and ($cwd | length) > 0
      then ($cwd | sub("/+$"; "")) + "/" + .
      else . end;
    def flush:
      if .current == null then . else .files += [.current] | .current = null end;
    . as $root
    | reduce (.tool_input.command | split("\n")[]) as $line
        ({files:[], current:null};
         if ($line | test("^\\*\\*\\* (Add|Update|Delete) File: .+$")) then
           ($line | capture("^\\*\\*\\* (?<op>Add|Update|Delete) File: (?<path>.+)$")) as $h
           | flush
           | .current = {kind:$h.op, path:$h.path, move_to:null, added:[], removed:[]}
         elif $line == "*** End Patch" then flush
         elif .current != null and ($line | startswith("*** Move to: ")) then
           .current.move_to = ($line | sub("^\\*\\*\\* Move to: "; ""))
         elif .current != null and ($line | startswith("+")) then
           .current.added += [$line[1:]]
         elif .current != null and ($line | startswith("-")) then
           .current.removed += [$line[1:]]
         else . end)
    | flush | .files[] as $file
    | (if $file.move_to == null then [$file.path] else [$file.path, $file.move_to] end)[] as $path
    | $root
    | .tool_name = (if $file.kind == "Add" then "Write" else "Edit" end)
    | .tool_input = ({
        file_path:($path | absolute($root.cwd)),
        old_string:($file.removed | join("\n")),
        new_string:($file.added | join("\n"))
      }
      + (if $file.kind == "Add" then {content:($file.added | join("\n"))} else {} end)
      + (if $file.move_to != null then {
          old_file_path:($file.path | absolute($root.cwd)),
          new_file_path:($file.move_to | absolute($root.cwd))
        } else {} end))
  ' 2>/dev/null) || exit 0

  CONTEXTS=""
  SYSTEM_MESSAGES=""
  while IFS= read -r payload; do
    [[ -n "$payload" ]] || continue
    run_wrapped "$payload"
    translate_result 1
    [[ -n "$TRANSLATED" ]] || continue
    if is_block_output "$TRANSLATED"; then
      printf '%s\n' "$TRANSLATED"
      exit 0
    fi
    context=$(printf '%s' "$TRANSLATED" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null) || exit 0
    system=$(printf '%s' "$TRANSLATED" | jq -r '.systemMessage // empty' 2>/dev/null) || exit 0
    [[ -z "$context" ]] || CONTEXTS+="${CONTEXTS:+$'\n\n'}$context"
    [[ -z "$system" ]] || SYSTEM_MESSAGES+="${SYSTEM_MESSAGES:+$'\n\n'}$system"
  done <<< "$PATCH_PAYLOADS"
  if [[ -n "$CONTEXTS" ]]; then
    jq -n --arg event "$EVENT" --arg context "$CONTEXTS" --arg system "$SYSTEM_MESSAGES" \
      '({} + if $system != "" then {systemMessage:$system} else {} end)
       + {hookSpecificOutput:{hookEventName:$event,additionalContext:$context}}'
  elif [[ -n "$SYSTEM_MESSAGES" ]]; then
    jq -n --arg system "$SYSTEM_MESSAGES" '{systemMessage:$system}'
  fi
  exit 0
fi

run_wrapped "$NORMALIZED"
translate_result 0
[[ -z "$TRANSLATED" ]] || printf '%s\n' "$TRANSLATED"
exit 0
