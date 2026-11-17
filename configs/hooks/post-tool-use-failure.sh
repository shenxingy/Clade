#!/bin/bash
# post-tool-use-failure.sh — Inject diagnostic context when a tool fails.
# exists-for: no incident recorded (added 2026-04-08 in 54237d7; Hooks gap 6, docs/archive/BRAINSTORM-resolved.md); need: a recovery hint the moment a tool call fails · retire-when: an ablation shows failed tool calls take no more recovery turns without the hint
# Hooks §Gap 6: Reduces recovery turns by providing immediate context on failure.
# Event: PostToolUseFailure — fires after a tool returns an error.
# Output: additionalContext injected as a system reminder for Claude to act on.
#
# No blocking (exit 0 always). Async-compatible (short timeout).
#
# The hint follows the tool's own error (the `error` field of the hook input),
# not the tool's name. Until 2026-11-09 every Read failure was answered "File
# not found … use Glob", so a Read refused for exceeding the token limit — a
# file that exists — was told to go looking for it, with a tool that a
# restricted session may not have. A hint that contradicts the error costs a
# turn; an error this hook does not recognise now gets no hint at all.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || echo "")
ERROR=$(echo "$INPUT" | jq -r '.error // ""' 2>/dev/null || echo "")
ERROR_LC=$(printf '%s' "$ERROR" | tr '[:upper:]' '[:lower:]')
BASE=${FILE_PATH##*/}
# Name a search that works whichever tools this session was given.
LOCATE="locate it with Glob(pattern='**/${BASE}') where Glob is available, or find . -name '${BASE}' through Bash"
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""' 2>/dev/null || echo "")
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // ""' 2>/dev/null || echo "")

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
    case "$ERROR_LC" in
      *"has not been read"*|*"modified since read"*)
        context="[Edit failure recovery hints]
- Read $FILE_PATH (again), then retry the Edit against the text it holds now" ;;
      *"matches of the string to replace"*)
        context="[Edit failure recovery hints]
- old_string occurs more than once in $FILE_PATH: add surrounding lines until it is unique, or set replace_all if every occurrence should change" ;;
      *)
        if [[ -n "$FILE_PATH" && -f "$FILE_PATH" ]]; then
          LINE_COUNT=$(wc -l < "$FILE_PATH" 2>/dev/null || echo "?")
          context="[Edit failure recovery hints]
- File exists: $FILE_PATH ($LINE_COUNT lines)
- Most common cause: old_string not found verbatim (whitespace/indent mismatch, or file changed since last Read)
- Fix: re-read the relevant section with Read tool, then retry Edit with exact string match"
        else
          context="[Edit failure recovery hints]
- File not found or path invalid: $FILE_PATH
- Before editing, $LOCATE"
        fi ;;
    esac
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
    case "$ERROR_LC" in
      *"exceeds maximum allowed tokens"*|*"exceeds maximum allowed size"*)
        context="[Read failure recovery hints]
- $FILE_PATH exists but is too large for one Read
- Read it in parts with offset and limit, or find the lines you need first (grep -n through Bash, or Grep where it is available)" ;;
      *eisdir*|*"is a directory"*)
        context="[Read failure recovery hints]
- $FILE_PATH is a directory, not a file: list it (ls through Bash, or Glob where it is available) and Read a file inside it" ;;
      ''|*"does not exist"*|*"no such file"*|*enoent*)
        # An empty error is an older Claude Code that did not send the field;
        # not-found is still the most common Read failure.
        context="[Read failure recovery hints]
- File not found: $FILE_PATH
- $LOCATE" ;;
      *)
        exit 0 ;;
    esac
    ;;

  *)
    # For unknown tools, emit nothing — avoid noisy context on every minor failure
    exit 0
    ;;
esac

[[ -n "$context" ]] || exit 0

# ─── Say each hint once per thread ───────────────────────────────────
# Measured 2026-10-20 → 10-26 over every transcript on the author's machine:
# this hook delivered 1,788 Bash hints (731k chars) to 46 sessions, and 845 of
# them (47%, 346k chars) were byte-identical to a hint the same thread had
# already received — up to 30 in one thread. The Bash hint is the cwd's git
# status and last two commits plus a fixed sentence, so it changes only when
# the tree does, and every failing `grep` or test run re-sent it. A repeat
# tells the model nothing new, so it is dropped. The key is session_id plus
# agent_id: a subagent has its own context and has not seen the parent's hints.
# Fails open — no session_id, or no private scratch dir — and emits as before.
if [[ -n "$SESSION_ID" ]]; then
  _rt_lib="$(cd "$(dirname "$0")" && pwd)/lib/runtime-dir.sh"
  # shellcheck source=/dev/null
  [[ -f "$_rt_lib" ]] && . "$_rt_lib" 2>/dev/null
  _seen_dir=""
  if declare -f clade_state_dir >/dev/null 2>&1; then
    _seen_dir=$(clade_state_dir claude-failure-hints 2>/dev/null) || _seen_dir=""
  fi
  if [[ -n "$_seen_dir" ]]; then
    _key="${SESSION_ID}.${AGENT_ID:-main}"
    _seen="$_seen_dir/${_key//[^A-Za-z0-9_.-]/_}"
    _sum=$(printf '%s' "$context" | cksum)
    if [[ -f "$_seen" ]] && grep -qxF -- "$_sum" "$_seen" 2>/dev/null; then
      exit 0
    fi
    printf '%s\n' "$_sum" >> "$_seen" 2>/dev/null
  fi
fi

jq -n --arg ctx "$context" \
  '{"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": $ctx}}'

exit 0
