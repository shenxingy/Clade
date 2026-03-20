#!/usr/bin/env bash
# memory-sync.sh — Auto-push after writes to synced ~/.claude/ directories (PostToolUse, async)
#
# Triggers sync-push.sh when Claude writes/edits a file under any synced dir:
#   ~/.claude/memory/             (global memory)
#   ~/.claude/projects/*/memory/  (project memory)
#   ~/.claude/skills/             (skills)
#   ~/.claude/hooks/              (hooks)
#   ~/.claude/scripts/            (scripts)
#   ~/.claude/corrections/        (corrections)
#
# Non-blocking: runs sync-push in background.

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"

# Skip entirely if sync not configured
[[ -f "$SYNC_CONFIG" ]] || exit 0

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

[[ -z "$FILE_PATH" ]] && exit 0

# Expand ~ to $HOME
FILE_PATH="${FILE_PATH/#\~/$HOME}"

# ─── Check if file is under a synced directory ───────────────────────────────

is_synced_path=false

for synced_dir in memory skills hooks scripts corrections; do
  if [[ "$FILE_PATH" == "$CLAUDE_DIR/$synced_dir/"* ]]; then
    is_synced_path=true
    break
  fi
done

# Also catch project memory paths
if [[ "$FILE_PATH" =~ ^$CLAUDE_DIR/projects/[^/]+/memory/ ]]; then
  is_synced_path=true
fi

[[ "$is_synced_path" == false ]] && exit 0

# ─── Trigger async push ──────────────────────────────────────────────────────

SYNC_PUSH="$CLAUDE_DIR/scripts/sync-push.sh"
[[ -x "$SYNC_PUSH" ]] || exit 0

"$SYNC_PUSH" &>/dev/null &
disown

exit 0
