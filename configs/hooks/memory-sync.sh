#!/usr/bin/env bash
# memory-sync.sh — Auto-push after memory file writes (PostToolUse, async)
#
# Triggers sync-push.sh when Claude writes/edits a file under:
#   ~/.claude/memory/           (global memory)
#   ~/.claude/projects/*/memory/ (project memory)
#
# Non-blocking: runs sync-push in background.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

[[ -z "$FILE_PATH" ]] && exit 0

# Expand ~ to $HOME
FILE_PATH="${FILE_PATH/#\~/$HOME}"

CLAUDE_DIR="$HOME/.claude"

# ─── Check if file is under a memory directory ───────────────────────────────

is_memory_path=false

if [[ "$FILE_PATH" == "$CLAUDE_DIR/memory/"* ]]; then
  is_memory_path=true
elif [[ "$FILE_PATH" =~ ^$CLAUDE_DIR/projects/[^/]+/memory/ ]]; then
  is_memory_path=true
fi

[[ "$is_memory_path" == false ]] && exit 0

# ─── Trigger async push ──────────────────────────────────────────────────────

SYNC_PUSH="$CLAUDE_DIR/scripts/sync-push.sh"
[[ -x "$SYNC_PUSH" ]] || exit 0

"$SYNC_PUSH" &>/dev/null &
disown

exit 0
