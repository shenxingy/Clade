#!/bin/bash
# post-tool-use-failure.sh — Inject diagnostic context when a tool fails.
# Hooks §Gap 6: Reduces recovery turns by providing immediate context on failure.
# Event: PostToolUseFailure — fires after a tool returns an error.
# Output: additionalContext injected as a system reminder for Claude to act on.
#
# No blocking (exit 0 always). Async-compatible (short timeout).

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || echo "")

context=""

case "$TOOL_NAME" in
  Bash)
    GIT_STATUS=$(git status --short 2>/dev/null | head -8 || echo "")
    LAST_COMMIT=$(git log --oneline -2 2>/dev/null || echo "")
    context="[Bash failure recovery hints]
- git status: ${GIT_STATUS:-clean}
- last commits: ${LAST_COMMIT:-none}
- common fixes: verify syntax, check permissions, confirm cwd, check exit code expectations"
    ;;

  Edit|MultiEdit)
    if [[ -n "$FILE_PATH" && -f "$FILE_PATH" ]]; then
      LINE_COUNT=$(wc -l < "$FILE_PATH" 2>/dev/null || echo "?")
      context="[Edit failure recovery hints]
- File exists: $FILE_PATH ($LINE_COUNT lines)
- Most common cause: old_string not found verbatim (whitespace/indent mismatch, or file changed since last Read)
- Fix: re-read the relevant section with Read tool, then retry Edit with exact string match"
    else
      context="[Edit failure recovery hints]
- File not found or path invalid: $FILE_PATH
- Use Glob tool to locate the correct path before editing"
    fi
    ;;

  Write)
    DIR=$(dirname "$FILE_PATH" 2>/dev/null || echo "")
    if [[ -n "$DIR" && ! -d "$DIR" ]]; then
      context="[Write failure recovery hints]
- Parent directory does not exist: $DIR
- Create it with: mkdir -p $DIR"
    else
      context="[Write failure recovery hints]
- Check file path is valid and parent directory exists
- Ensure you have read the file with Read tool before writing (required by tool contract)"
    fi
    ;;

  Read)
    context="[Read failure recovery hints]
- File not found: $FILE_PATH
- Use Glob to locate the file: Glob(pattern='**/${FILE_PATH##*/}')
- Or use Grep to search for related files"
    ;;

  *)
    # For unknown tools, emit nothing — avoid noisy context on every minor failure
    exit 0
    ;;
esac

if [[ -n "$context" ]]; then
  jq -n --arg ctx "$context" \
    '{"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": $ctx}}'
fi

exit 0
